"""Mini-framework de validation : cas de test, contexte d'exécution, preuves.

Chaque cas de test s'exécute sur un banc neuf (CockpitRuntime) avec la build à
qualifier, comme si on reflashait le calculateur avant chaque test.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from ..app.runtime import CockpitRuntime
from ..builds import Build
from ..bus import DATABASE


class Status(str, Enum):
    PASSED = "Réussi"
    FAILED = "Échoué"
    ERROR = "Erreur"
    SKIPPED = "Non exécuté"


SEVERITIES = ("bloquant", "majeur", "mineur")

CATEGORIES = {
    "sanity": "Sanity Check",
    "non_regression": "Non-régression",
    "endurance": "Endurance",
    "performance": "Performance",
}


@dataclass(frozen=True)
class TestCase:
    id: str
    title: str
    category: str
    severity: str
    requirement: str
    func: Callable[["TestContext"], None]
    dt: float = 0.02

    def __post_init__(self):
        assert self.category in CATEGORIES, self.category
        assert self.severity in SEVERITIES, self.severity


@dataclass
class Step:
    text: str
    ok: bool | None  # None = action, True/False = vérification


@dataclass
class TestResult:
    case: TestCase
    status: Status
    duration_s: float = 0.0
    sim_time_s: float = 0.0
    steps: list[Step] = field(default_factory=list)
    measures: dict[str, str] = field(default_factory=dict)
    message: str = ""
    evidence: dict[str, object] = field(default_factory=dict)
    expected: str = ""
    observed: str = ""

    @property
    def failed(self) -> bool:
        return self.status in (Status.FAILED, Status.ERROR)


class CheckFailed(AssertionError):
    def __init__(self, expected: str, observed: str = ""):
        super().__init__(expected + (f" — {observed}" if observed else ""))
        self.expected = expected
        self.observed = observed


class TestContext:
    def __init__(self, case: TestCase, build: Build):
        self.case = case
        self.build = build
        self.rt = CockpitRuntime(build=build)
        self.steps: list[Step] = []
        self.measures: dict[str, str] = {}

    # Raccourcis
    @property
    def state(self):
        return self.rt.state

    @property
    def vehicle(self):
        return self.rt.vehicle

    def step(self, text: str) -> None:
        self.steps.append(Step(text, None))

    def run(self, seconds: float, text: str | None = None) -> None:
        if text:
            self.step(text)
        self.rt.run_for(seconds, self.case.dt)

    def run_until(self, condition: Callable[[], bool], timeout_s: float) -> float | None:
        """Avance la simulation jusqu'à ce que la condition soit vraie. Retourne le délai."""
        start = self.rt.clock.now()
        while self.rt.clock.now() - start < timeout_s:
            self.rt.step(self.case.dt)
            if condition():
                return self.rt.clock.now() - start
        return None

    def measure(self, name: str, value: float | str, unit: str = "") -> None:
        text = f"{value:.2f}" if isinstance(value, float) else str(value)
        self.measures[name] = f"{text} {unit}".strip()

    def check(self, condition: bool, text: str, detail: str = "") -> None:
        self.steps.append(Step(text, bool(condition)))
        if not condition:
            raise CheckFailed(text, detail)

    # Raccourcis de conduite
    def start_vehicle(self, gear: str = "D") -> None:
        self.step(f"Démarrer le véhicule et engager {gear}")
        self.vehicle.power_on()
        self.vehicle.inputs.requested_gear = gear
        self.rt.run_for(0.3, self.case.dt)

    def collect_evidence(self) -> dict[str, object]:
        frames = []
        for frame in self.rt.bus.recent(15):
            message = DATABASE.by_id(frame.arbitration_id)
            frames.append(f"{frame.timestamp:8.3f}  0x{frame.arbitration_id:03X}  "
                          f"{(message.name if message else '?'):<13} {frame.data.hex(' ').upper()}")
        s = self.state
        return {
            "Temps simulé": f"{self.rt.clock.now():.3f} s",
            "État véhicule": (f"vitesse={s.speed_kmh:.1f} km/h, rapport={s.gear}, ready={s.ready}, "
                              f"SOC={s.soc_pct:.1f} %, autonomie={s.range_km} km"),
            "Trames en timeout": ", ".join(sorted(s.stale)) or "aucune",
            "Trames jamais reçues": ", ".join(
                m.name for m in DATABASE.messages if m.name not in s.received) or "aucune",
            "Alertes actives": ", ".join(a.code for a in s.alerts) or "aucune",
            "Dernières trames CAN": frames,
        }


def execute(case: TestCase, build: Build) -> TestResult:
    ctx = TestContext(case, build)
    started = time.perf_counter()
    status, message, evidence, expected, observed = Status.PASSED, "", {}, "", ""
    try:
        case.func(ctx)
    except CheckFailed as exc:
        status, message, evidence = Status.FAILED, str(exc), ctx.collect_evidence()
        expected, observed = exc.expected, exc.observed or "Condition non vérifiée"
    except Exception as exc:  # erreur dans le test lui-même, pas dans la build
        status = Status.ERROR
        message = f"{type(exc).__name__}: {exc}"
        evidence = {"Trace Python": traceback.format_exc().splitlines()[-6:]}
    finally:
        ctx.rt.shutdown()
    return TestResult(case, status, time.perf_counter() - started, ctx.rt.clock.now(),
                      ctx.steps, ctx.measures, message, evidence, expected, observed)


REGISTRY: list[TestCase] = []


def case(id: str, title: str, category: str, severity: str, requirement: str, dt: float = 0.02):
    """Décorateur qui enregistre un cas de test dans le catalogue."""
    def register(func):
        if any(c.id == id for c in REGISTRY):
            raise ValueError(f"Identifiant de test en double : {id}")
        REGISTRY.append(TestCase(id, title, category, severity, requirement, func, dt))
        return func
    return register
