"""Bus CAN virtuel en mémoire : aucune dépendance, déterministe, idéal pour les tests."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CanFrame:
    arbitration_id: int
    data: bytes
    timestamp: float = 0.0


FrameCallback = Callable[[CanFrame], None]


class VirtualBus:
    """Diffuse chaque trame envoyée à tous les abonnés et la garde dans une trace."""

    def __init__(self, clock: Callable[[], float] | None = None, trace_size: int = 5000):
        self._clock = clock or time.monotonic
        self._subscribers: list[FrameCallback] = []
        self._lock = threading.Lock()
        self._trace: deque[CanFrame] = deque(maxlen=trace_size)
        self.frames_sent = 0

    def subscribe(self, callback: FrameCallback) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def send(self, arbitration_id: int, data: bytes) -> None:
        self._deliver(CanFrame(arbitration_id, bytes(data), self._clock()))

    def _deliver(self, frame: CanFrame) -> None:
        with self._lock:
            self._trace.append(frame)
            self.frames_sent += 1
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(frame)

    def recent(self, count: int = 50) -> list[CanFrame]:
        with self._lock:
            return list(self._trace)[-count:]

    def clear_trace(self) -> None:
        with self._lock:
            self._trace.clear()

    def shutdown(self) -> None:
        pass
