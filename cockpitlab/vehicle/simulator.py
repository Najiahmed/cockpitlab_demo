"""Simulateur de véhicule électrique.

Il joue le rôle des calculateurs (ESP, VCU, BMS, BCM, ACU) : il calcule l'état
physique du véhicule à partir des actions du conducteur, puis émet les trames
CAN à leur période respective.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..bus import DATABASE, Database, VirtualBus

KMH = 3.6


@dataclass
class DriverInputs:
    accelerator: float = 0.0  # 0..1
    brake: float = 0.0        # 0..1
    requested_gear: str = "P"
    left_turn: bool = False
    right_turn: bool = False
    hazard: bool = False
    low_beam: bool = False
    high_beam: bool = False
    seatbelt_buckled: bool = True


class VehicleSimulator:
    MASS_KG = 1700.0
    MAX_POWER_KW = 160.0
    MAX_ACCEL = 3.5          # m/s²
    MAX_BRAKE = 9.0          # m/s²
    REGEN_DECEL = 1.0        # m/s², pied levé
    MAX_SPEED_KMH = 170.0
    MAX_REVERSE_KMH = 20.0
    SHIFT_SPEED_LIMIT_KMH = 5.0
    BATTERY_KWH = 52.0
    AVG_CONSUMPTION_KWH_PER_KM = 0.165
    AUX_POWER_KW = 0.6
    REGEN_EFFICIENCY = 0.6

    def __init__(self, bus: VirtualBus, database: Database = DATABASE, soc_pct: float = 80.0,
                 faults: frozenset[str] = frozenset()):
        self.bus = bus
        self.faults = faults
        self.database = database
        self.reset(soc_pct)

    def reset(self, soc_pct: float = 80.0) -> None:
        """Remet le véhicule dans un état connu (préconditions d'un scénario)."""
        self.muted: set[str] = set()      # trames coupées (injection de défauts)
        self.corrupted: set[str] = set()  # trames émises avec une charge utile corrompue
        if hasattr(self, "inputs"):  # même objet : les écrans qui le référencent restent branchés
            self.inputs.__dict__.update(DriverInputs().__dict__)
        else:
            self.inputs = DriverInputs()
        self.ready = False
        self.gear = "P"
        self.speed_ms = 0.0
        self.power_kw = 0.0
        self.soc_pct = soc_pct
        self.battery_temp_c = 24.0
        self.odometer_km = 0.0
        self.last_rejection: str | None = None
        self._since_sent = {m.name: float("inf") for m in self.database.messages}

    # --- commandes -------------------------------------------------------
    def power_on(self) -> None:
        self.ready = True

    def power_off(self) -> None:
        if self.speed_kmh > self.SHIFT_SPEED_LIMIT_KMH:
            self.last_rejection = "Arrêt refusé : véhicule en mouvement"
            return
        self.ready = False
        self.gear = "P"
        self.inputs.requested_gear = "P"

    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * KMH

    @property
    def range_km(self) -> int:
        energy = self.soc_pct / 100 * self.BATTERY_KWH
        offset = 15 if "RANGE_OFFSET" in self.faults else 0
        return int(energy / self.AVG_CONSUMPTION_KWH_PER_KM) + offset

    @property
    def max_reverse_kmh(self) -> float:
        return 40.0 if "REVERSE_LIMIT_BROKEN" in self.faults else self.MAX_REVERSE_KMH

    def cycle_s(self, message) -> float:
        if message.name == "ESP_Speed" and "ESP_SLOW_CYCLE" in self.faults:
            return 0.026
        return message.cycle_ms / 1000

    # --- boucle ----------------------------------------------------------
    def step(self, dt: float) -> None:
        self._update_gear()
        self._update_motion(dt)
        self._update_battery(dt)
        self._send_due_frames(dt)

    def _update_gear(self) -> None:
        requested = self.inputs.requested_gear
        if requested == self.gear:
            return
        if not self.ready and requested != "P":
            self.last_rejection = "Changement de rapport refusé : véhicule non démarré"
        elif requested != "N" and self.speed_kmh > self.SHIFT_SPEED_LIMIT_KMH:
            self.last_rejection = (
                f"Passage en {requested} refusé au-dessus de "
                f"{self.SHIFT_SPEED_LIMIT_KMH:.0f} km/h"
            )
        else:
            self.gear = requested
            self.last_rejection = None
            return
        # Une demande refusée est oubliée : elle ne doit pas s'appliquer plus tard.
        self.inputs.requested_gear = self.gear

    def _update_motion(self, dt: float) -> None:
        v = self.speed_ms
        driving = self.ready and self.gear in ("D", "R") and self.soc_pct > 0
        traction = 0.0
        if driving:
            power_limited = self.MAX_POWER_KW * 1000 / (self.MASS_KG * max(v, 1.0))
            traction = self.inputs.accelerator * min(self.MAX_ACCEL, power_limited)

        drag = (0.15 + 0.0004 * v * v) if v > 0 else 0.0
        brake = self.inputs.brake * self.MAX_BRAKE
        regen = self.REGEN_DECEL if (driving and self.inputs.accelerator == 0 and v > 0) else 0.0
        if self.gear == "P":
            brake = max(brake, 10.0)

        v = max(0.0, v + (traction - drag - brake - regen) * dt)
        limit = self.max_reverse_kmh if self.gear == "R" else self.MAX_SPEED_KMH
        v = min(v, limit / KMH)

        self.speed_ms = v
        self.odometer_km += v * dt / 1000
        if traction > 0:
            self.power_kw = self.MASS_KG * v * (traction + 0.05) / 1000
        elif regen > 0 or (brake > 0 and driving):
            self.power_kw = -self.MASS_KG * v * min(regen + brake, 3.0) / 1000 * self.REGEN_EFFICIENCY
        else:
            self.power_kw = 0.0
        self.power_kw = max(-50.0, min(self.MAX_POWER_KW, self.power_kw))

    def _update_battery(self, dt: float) -> None:
        if not self.ready:
            return
        energy_kwh = (self.power_kw + self.AUX_POWER_KW) * dt / 3600
        self.soc_pct = max(0.0, min(100.0, self.soc_pct - energy_kwh / self.BATTERY_KWH * 100))
        self.battery_temp_c = min(45.0, self.battery_temp_c + max(self.power_kw, 0) * dt * 1e-4)

    # --- émission CAN ----------------------------------------------------
    def signal_values(self) -> dict[str, dict]:
        blink = self.inputs.hazard
        return {
            "ESP_Speed": {"speed_kmh": self.speed_kmh},
            "VCU_Status": {"gear": self.gear, "ready": self.ready, "power_kw": self.power_kw},
            "BMS_Battery": {
                "soc_pct": self.soc_pct,
                "range_km": self.range_km,
                "battery_temp_c": self.battery_temp_c,
            },
            "BCM_Lights": {
                "left_turn": self.inputs.left_turn or blink,
                "right_turn": self.inputs.right_turn or blink,
                "hazard": self.inputs.hazard,
                "low_beam": self.inputs.low_beam,
                "high_beam": self.inputs.high_beam,
            },
            "ACU_Seatbelt": {"seatbelt_buckled": self.inputs.seatbelt_buckled},
        }

    def _send_due_frames(self, dt: float) -> None:
        values = None
        for message in self.database.messages:
            if message.name in self.muted:
                continue
            if message.name == "VCU_Status" and "VCU_SILENT" in self.faults:
                continue
            self._since_sent[message.name] += dt
            if self._since_sent[message.name] + 1e-9 < self.cycle_s(message):
                continue
            values = values or self.signal_values()
            data = message.encode(values[message.name])
            if message.name in self.corrupted:
                data = b"\xff" * message.dlc  # charge utile écrasée (défaut matériel ou logiciel)
            self.bus.send(message.frame_id, data)
            self._since_sent[message.name] = 0.0
