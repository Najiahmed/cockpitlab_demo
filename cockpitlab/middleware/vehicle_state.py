"""Middleware cockpit : décode les trames CAN et expose un état véhicule aux écrans.

C'est l'équivalent simplifié de la couche « Vehicle HAL » d'Android Automotive :
les applications ne lisent jamais le CAN directement, elles lisent cet état.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Callable

from ..bus import DATABASE, CanFrame, Database, VirtualBus

LOW_BATTERY_PCT = 15.0
SEATBELT_SPEED_KMH = 10.0
MAX_SPEED_STEP_KMH = 30.0   # saut de vitesse maximal plausible entre deux trames proches
RATE_CHECK_WINDOW_S = 0.5


def _plausible(name: str, values: dict, previous: "VehicleState", dt_since_valid: float | None) -> bool:
    """Contrôle de plausibilité : une trame incohérente est rejetée, pas affichée."""
    if name == "ESP_Speed":
        speed = values["speed_kmh"]
        if not 0 <= speed <= 250:
            return False
        if dt_since_valid is not None and dt_since_valid <= RATE_CHECK_WINDOW_S:
            return abs(speed - previous.speed_kmh) <= MAX_SPEED_STEP_KMH
        return True
    if name == "BMS_Battery":
        return (0 <= values["soc_pct"] <= 100 and values["range_km"] <= 1000
                and -40 <= values["battery_temp_c"] <= 100)
    if name == "VCU_Status":
        return -100 <= values["power_kw"] <= 250
    return True  # trames sans grandeur physique contrôlable (états binaires)


@dataclass(frozen=True)
class Alert:
    code: str
    level: str  # "info" | "warning" | "critical"
    text: str


@dataclass(frozen=True)
class VehicleState:
    speed_kmh: float = 0.0
    gear: str = "P"
    ready: bool = False
    power_kw: float = 0.0
    soc_pct: float = 0.0
    range_km: int = 0
    battery_temp_c: float = 0.0
    left_turn: bool = False
    right_turn: bool = False
    hazard: bool = False
    low_beam: bool = False
    high_beam: bool = False
    seatbelt_buckled: bool = True
    received: frozenset[str] = frozenset()  # messages reçus au moins une fois
    stale: frozenset[str] = frozenset()     # messages en timeout
    invalid: frozenset[str] = frozenset()   # dernière trame reçue rejetée (incohérente)
    alerts: tuple[Alert, ...] = field(default_factory=tuple)

    def is_valid(self, message_name: str) -> bool:
        return (message_name in self.received and message_name not in self.stale
                and message_name not in self.invalid)

    def has_alert(self, code: str) -> bool:
        return any(a.code == code for a in self.alerts)


class VehicleStateService:
    def __init__(self, bus: VirtualBus, database: Database = DATABASE,
                 faults: frozenset[str] = frozenset()):
        self.database = database
        self.faults = faults
        self._state = VehicleState()
        self._last_rx: dict[str, float] = {}     # dernière trame reçue (sert aux timeouts)
        self._last_valid: dict[str, float] = {}  # dernière trame acceptée (sert à la plausibilité)
        self._started_at: float | None = None
        self._lock = threading.Lock()
        self._listeners: list[Callable[[VehicleState], None]] = []
        self.unknown_frames = 0
        self.decode_errors = 0
        self.rejected_frames = 0
        bus.subscribe(self._on_frame)

    def snapshot(self) -> VehicleState:
        with self._lock:
            return self._state

    def add_listener(self, callback: Callable[[VehicleState], None]) -> None:
        self._listeners.append(callback)

    def _on_frame(self, frame: CanFrame) -> None:
        message = self.database.by_id(frame.arbitration_id)
        if message is None:
            self.unknown_frames += 1
            return
        try:
            values = message.decode(frame.data)
        except Exception:
            self.decode_errors += 1
            return
        with self._lock:
            self._last_rx[message.name] = frame.timestamp
            last = self._last_valid.get(message.name)
            dt = None if last is None else frame.timestamp - last
            if not _plausible(message.name, values, self._state, dt):
                self.rejected_frames += 1
                if message.name in self._state.invalid and message.name not in self._state.stale:
                    return
                state = replace(self._state, invalid=self._state.invalid | {message.name},
                                stale=self._state.stale - {message.name})
                self._state = replace(state, alerts=compute_alerts(state, self.faults))
                new_state = self._state
            else:
                self._last_valid[message.name] = frame.timestamp
                state = replace(
                    self._state,
                    **values,
                    received=self._state.received | {message.name},
                    stale=self._state.stale - {message.name},
                    invalid=self._state.invalid - {message.name},
                )
                self._state = replace(state, alerts=compute_alerts(state, self.faults))
                new_state = self._state
        self._notify(new_state)

    def check_timeouts(self, now: float) -> None:
        """Une trame jamais reçue est comptée depuis le premier contrôle (mise sous tension)."""
        with self._lock:
            if self._started_at is None:
                self._started_at = now
            stale = frozenset(
                m.name for m in self.database.messages
                if now - self._last_rx.get(m.name, self._started_at) > m.timeout_s
            )
            if stale == self._state.stale:
                return
            state = replace(self._state, stale=stale)
            self._state = replace(state, alerts=compute_alerts(state, self.faults))
            new_state = self._state
        self._notify(new_state)

    def _notify(self, state: VehicleState) -> None:
        for callback in self._listeners:
            callback(state)


def compute_alerts(state: VehicleState, faults: frozenset[str] = frozenset()) -> tuple[Alert, ...]:
    """Règles d'alerte du combiné. Chaque règle est testée unitairement."""
    alerts: list[Alert] = []
    for name in sorted(state.stale):
        alerts.append(Alert(f"SIGNAL_LOST:{name}", "critical", f"Communication perdue : {name}"))
    for name in sorted(state.invalid - state.stale):
        alerts.append(Alert(f"DATA_INVALID:{name}", "critical", f"Donnée incohérente : {name}"))
    if state.is_valid("BMS_Battery") and state.soc_pct < LOW_BATTERY_PCT:
        alerts.append(Alert("LOW_BATTERY", "warning", "Batterie faible : rechargez bientôt"))
    if ("SEATBELT_ALERT_MISSING" not in faults
            and state.ready and state.is_valid("ACU_Seatbelt") and state.is_valid("ESP_Speed")
            and not state.seatbelt_buckled and state.speed_kmh > SEATBELT_SPEED_KMH):
        alerts.append(Alert("SEATBELT", "critical", "Bouclez votre ceinture"))
    if state.is_valid("BMS_Battery") and state.battery_temp_c >= 42:
        alerts.append(Alert("BATTERY_HOT", "warning", "Température batterie élevée"))
    return tuple(alerts)
