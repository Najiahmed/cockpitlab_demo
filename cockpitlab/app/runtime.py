"""Assemble le bus, le simulateur et le middleware. Utilisé par l'interface ET par les tests."""
from __future__ import annotations

from ..builds import REFERENCE_BUILD, Build
from ..bus import create_bus
from ..middleware import VehicleState, VehicleStateService
from ..vehicle import VehicleSimulator


class SimClock:
    def __init__(self) -> None:
        self._t = 0.0

    def now(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


class CockpitRuntime:
    def __init__(self, backend: str = "memory", soc_pct: float = 80.0,
                 build: Build = REFERENCE_BUILD):
        self.build = build
        self.clock = SimClock()
        self.bus = create_bus(backend, clock=self.clock.now)
        self.state_service = VehicleStateService(self.bus, faults=build.faults)
        self.vehicle = VehicleSimulator(self.bus, soc_pct=soc_pct, faults=build.faults)

    def install_build(self, build: Build) -> None:
        """Change la build installée sur le banc, à chaud (comme un reflash)."""
        self.build = build
        self.vehicle.faults = build.faults
        self.state_service.faults = build.faults

    @property
    def state(self) -> VehicleState:
        return self.state_service.snapshot()

    def step(self, dt: float) -> None:
        self.clock.advance(dt)
        self.vehicle.step(dt)
        self.state_service.check_timeouts(self.clock.now())

    def run_for(self, seconds: float, dt: float = 0.02) -> None:
        for _ in range(round(seconds / dt)):
            self.step(dt)

    def shutdown(self) -> None:
        self.bus.shutdown()
