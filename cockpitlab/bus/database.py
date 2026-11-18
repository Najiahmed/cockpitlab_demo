"""Base de signaux CAN du véhicule simulé (équivalent simplifié d'un fichier DBC).

Toutes les trames, identifiants et noms de signaux sont inventés pour ce projet.
Codage Intel (little-endian), comme la plupart des bus CAN automobiles.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Signal:
    name: str
    start_bit: int
    length: int
    factor: float = 1.0
    offset: float = 0.0
    unit: str = ""
    choices: dict[int, str] | None = None

    @property
    def raw_max(self) -> int:
        return (1 << self.length) - 1

    @property
    def is_flag(self) -> bool:
        return self.length == 1 and self.choices is None

    def to_raw(self, value: Any) -> int:
        """Valeur physique -> valeur brute, bornée à la taille du signal."""
        if self.choices is not None:
            inverse = {label: raw for raw, label in self.choices.items()}
            if value not in inverse:
                raise ValueError(f"{self.name}: valeur inconnue {value!r}")
            return inverse[value]
        raw = round((float(value) - self.offset) / self.factor)
        return max(0, min(self.raw_max, raw))

    def from_raw(self, raw: int) -> Any:
        """Valeur brute -> valeur physique."""
        if self.choices is not None:
            return self.choices.get(raw, f"INVALIDE({raw})")
        if self.is_flag:
            return bool(raw)
        value = raw * self.factor + self.offset
        if float(self.factor).is_integer() and float(self.offset).is_integer():
            return int(value)
        return round(value, 6)


@dataclass(frozen=True)
class Message:
    name: str
    frame_id: int
    cycle_ms: int
    signals: tuple[Signal, ...]
    sender: str = ""
    dlc: int = 8

    def encode(self, values: dict[str, Any]) -> bytes:
        raw = 0
        for signal in self.signals:
            if signal.name not in values:
                raise KeyError(f"{self.name}: signal manquant {signal.name}")
            raw |= signal.to_raw(values[signal.name]) << signal.start_bit
        return raw.to_bytes(self.dlc, "little")

    def decode(self, data: bytes) -> dict[str, Any]:
        raw = int.from_bytes(data[: self.dlc], "little")
        return {
            s.name: s.from_raw((raw >> s.start_bit) & s.raw_max) for s in self.signals
        }

    @property
    def timeout_s(self) -> float:
        """Une trame est considérée perdue après 3 cycles sans réception."""
        return 3 * self.cycle_ms / 1000


GEARS = {0: "P", 1: "R", 2: "N", 3: "D"}

MESSAGES: tuple[Message, ...] = (
    Message(
        "ESP_Speed", 0x1A0, 20, sender="ESP",
        signals=(Signal("speed_kmh", 0, 16, 0.01, unit="km/h"),),
    ),
    Message(
        "VCU_Status", 0x0C8, 100, sender="VCU",
        signals=(
            Signal("gear", 0, 2, choices=GEARS),
            Signal("ready", 8, 1),
            Signal("power_kw", 16, 16, 0.1, -200.0, unit="kW"),
        ),
    ),
    Message(
        "BMS_Battery", 0x3B0, 500, sender="BMS",
        signals=(
            Signal("soc_pct", 0, 10, 0.1, unit="%"),
            Signal("range_km", 16, 10, unit="km"),
            Signal("battery_temp_c", 32, 8, offset=-40, unit="°C"),
        ),
    ),
    Message(
        "BCM_Lights", 0x2D0, 100, sender="BCM",
        signals=(
            Signal("left_turn", 0, 1),
            Signal("right_turn", 1, 1),
            Signal("hazard", 2, 1),
            Signal("low_beam", 3, 1),
            Signal("high_beam", 4, 1),
        ),
    ),
    Message(
        "ACU_Seatbelt", 0x2F0, 500, sender="ACU",
        signals=(Signal("seatbelt_buckled", 0, 1),),
    ),
)


class Database:
    def __init__(self, messages: tuple[Message, ...] = MESSAGES):
        self.messages = messages
        self._by_id = {m.frame_id: m for m in messages}
        self._by_name = {m.name: m for m in messages}
        if len(self._by_id) != len(messages):
            raise ValueError("Identifiants CAN en double")

    def by_id(self, frame_id: int) -> Message | None:
        return self._by_id.get(frame_id)

    def by_name(self, name: str) -> Message:
        return self._by_name[name]


DATABASE = Database()
