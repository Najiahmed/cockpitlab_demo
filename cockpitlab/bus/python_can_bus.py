"""Variante du bus qui passe par python-can (interface "virtual").

Deux ECU distincts partagent le même canal, comme sur un vrai réseau :
un bus d'émission (les calculateurs simulés) et un bus de réception (le cockpit).
Pour passer plus tard sur un vrai adaptateur (PCAN, Vector, socketcan),
il suffit de changer `interface` et `channel`.
"""
from __future__ import annotations

from typing import Callable

from .virtual_bus import CanFrame, VirtualBus


class PythonCanBus(VirtualBus):
    def __init__(self, clock: Callable[[], float] | None = None,
                 interface: str = "virtual", channel: str = "cockpitlab",
                 trace_size: int = 5000):
        super().__init__(clock=clock, trace_size=trace_size)
        import can  # import tardif : python-can reste optionnel

        self._can = can
        self._tx = can.Bus(interface=interface, channel=channel)
        self._rx = can.Bus(interface=interface, channel=channel)
        self._notifier = can.Notifier(self._rx, [self._on_message])

    def send(self, arbitration_id: int, data: bytes) -> None:
        message = self._can.Message(arbitration_id=arbitration_id, data=bytes(data),
                                    is_extended_id=False)
        self._tx.send(message)

    def _on_message(self, message) -> None:
        self._deliver(CanFrame(message.arbitration_id, bytes(message.data), self._clock()))

    def shutdown(self) -> None:
        self._notifier.stop()
        self._tx.shutdown()
        self._rx.shutdown()
