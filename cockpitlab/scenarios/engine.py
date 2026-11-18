"""Moteur de scénarios : séquences d'actions et de vérifications décrites en JSON.

Un scénario se joue soit en direct sur le cockpit (l'interface appelle `tick`
à chaque image), soit sans interface (`run_headless`, utilisé par pytest et la CI).

Format d'une étape (une seule clé d'action par étape) :
    {"label": "...", "action": "gear", "value": "D"}
    {"label": "...", "wait": 2.0}
    {"label": "...", "wait_until": {"speed_kmh": [">=", 50]}, "timeout": 15}
    {"label": "...", "expect": {"alert": "SEATBELT"}, "within": 1.0}
    {"label": "...", "expect": {"no_critical": true}, "during": 3.0}
    {"say": "Texte affiché à l'écran"}
"""
from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..app.runtime import CockpitRuntime
from ..bus import DATABASE

DATA_DIR = Path(__file__).parent / "data"

ACTIONS = {"power_on", "power_off", "gear", "accelerator", "brake", "release", "input",
           "soc", "battery_temp", "mute", "unmute", "corrupt", "repair"}
STEP_KINDS = ("action", "wait", "wait_until", "expect", "say")
OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le,
             "==": operator.eq, "!=": operator.ne}
SPECIAL_CONDITIONS = {"alert", "no_alert", "no_critical", "valid", "invalid", "rejected"}
STATE_FIELDS = {"speed_kmh", "gear", "ready", "power_kw", "soc_pct", "range_km", "battery_temp_c",
                "left_turn", "right_turn", "hazard", "low_beam", "high_beam", "seatbelt_buckled"}
INPUT_FIELDS = {"left_turn", "right_turn", "hazard", "low_beam", "high_beam", "seatbelt_buckled"}
MESSAGE_NAMES = {m.name for m in DATABASE.messages}


class ScenarioError(ValueError):
    pass


class StepStatus(str, Enum):
    PENDING = "En attente"
    RUNNING = "En cours"
    PASSED = "Réussi"
    FAILED = "Échoué"
    SKIPPED = "Non exécuté"


@dataclass(frozen=True)
class Step:
    kind: str
    label: str
    params: dict[str, Any]

    @property
    def is_check(self) -> bool:
        return self.kind in ("wait_until", "expect")


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    description: str
    steps: tuple[Step, ...]
    soc_pct: float = 80.0
    source: str = ""


# --------------------------------------------------------------------------
# Lecture et validation
# --------------------------------------------------------------------------
def _validate_condition(cond: Any, where: str) -> None:
    if not isinstance(cond, dict) or len(cond) != 1:
        raise ScenarioError(f"{where} : une condition contient exactement une clé")
    key, value = next(iter(cond.items()))
    if key in ("valid", "invalid") and value not in MESSAGE_NAMES:
        raise ScenarioError(f"{where} : trame inconnue {value!r}")
    if key not in SPECIAL_CONDITIONS and key not in STATE_FIELDS:
        raise ScenarioError(f"{where} : condition inconnue {key!r}")
    if isinstance(value, list) and (len(value) != 2 or value[0] not in OPERATORS):
        raise ScenarioError(f"{where} : comparaison attendue sous la forme [\"<=\", 20]")


def parse_step(raw: dict, index: int) -> Step:
    where = f"étape {index + 1}"
    kinds = [k for k in STEP_KINDS if k in raw]
    if len(kinds) != 1:
        raise ScenarioError(f"{where} : une étape contient une et une seule clé parmi {STEP_KINDS}")
    kind = kinds[0]
    if kind == "action":
        if raw["action"] not in ACTIONS:
            raise ScenarioError(f"{where} : action inconnue {raw['action']!r}")
        if raw["action"] in ("mute", "unmute", "corrupt", "repair") and raw.get("message") not in MESSAGE_NAMES:
            raise ScenarioError(f"{where} : trame inconnue {raw.get('message')!r}")
        if raw["action"] == "input":
            unknown = set(raw.get("values", {})) - INPUT_FIELDS
            if not raw.get("values") or unknown:
                raise ScenarioError(f"{where} : entrées inconnues {sorted(unknown)}")
    elif kind == "wait_until":
        _validate_condition(raw["wait_until"], where)
        if "timeout" not in raw:
            raise ScenarioError(f"{where} : wait_until demande un timeout")
    elif kind == "expect":
        _validate_condition(raw["expect"], where)
        if "within" in raw and "during" in raw:
            raise ScenarioError(f"{where} : within et during ne se combinent pas")
    label = raw.get("label") or (raw["say"] if kind == "say" else _default_label(kind, raw))
    return Step(kind, label, raw)


def _default_label(kind: str, raw: dict) -> str:
    if kind == "wait":
        return f"Attendre {raw['wait']} s"
    return f"{kind} {raw.get(kind)}"


def parse_scenario(data: dict, source: str = "") -> Scenario:
    for key in ("id", "title", "steps"):
        if key not in data:
            raise ScenarioError(f"{source or 'scénario'} : champ obligatoire manquant {key!r}")
    try:
        steps = tuple(parse_step(raw, i) for i, raw in enumerate(data["steps"]))
    except ScenarioError as exc:
        raise ScenarioError(f"{data['id']} : {exc}") from None
    return Scenario(data["id"], data["title"], data.get("description", ""), steps,
                    float(data.get("soc_pct", 80.0)), source)


def load_scenarios(directory: Path = DATA_DIR) -> list[Scenario]:
    scenarios = []
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            scenarios.append(parse_scenario(json.load(fh), path.name))
    ids = [s.id for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ScenarioError("Identifiants de scénarios en double")
    return scenarios


# --------------------------------------------------------------------------
# Exécution
# --------------------------------------------------------------------------
@dataclass
class StepResult:
    status: StepStatus = StepStatus.PENDING
    detail: str = ""


@dataclass
class ScenarioRun:
    scenario: Scenario
    build_version: str
    results: list[StepResult] = field(default_factory=list)
    sim_time_s: float = 0.0

    @property
    def passed(self) -> bool:
        return all(r.status == StepStatus.PASSED for r in self.results)

    @property
    def failed_step(self) -> int | None:
        return next((i for i, r in enumerate(self.results) if r.status == StepStatus.FAILED), None)


class ScenarioPlayer:
    def __init__(self, runtime: CockpitRuntime, scenario: Scenario):
        self.rt = runtime
        self.scenario = scenario
        self.run = ScenarioRun(scenario, runtime.build.version,
                               [StepResult() for _ in scenario.steps])
        self.index = 0
        self.elapsed = 0.0
        self.narration = scenario.title
        self.finished = False
        self._start_time = runtime.clock.now()
        runtime.vehicle.reset(scenario.soc_pct)  # préconditions connues

    # ------------------------------------------------------------------
    def tick(self, dt: float) -> None:
        """À appeler après chaque pas de simulation."""
        while not self.finished:
            step = self.scenario.steps[self.index]
            result = self.run.results[self.index]
            if result.status == StepStatus.PENDING:
                result.status = StepStatus.RUNNING
                self.elapsed = 0.0
                if step.kind != "say":
                    self.narration = step.label
            else:
                self.elapsed += dt
            done = self._advance(step, result)
            self.run.sim_time_s = self.rt.clock.now() - self._start_time
            if not done:
                return  # étape en cours : on attend le prochain pas
            if result.status == StepStatus.FAILED:
                self._abort()
                return
            self.index += 1
            if self.index == len(self.scenario.steps):
                self.finished = True
                self.narration = f"Scénario terminé : {self.scenario.title}"
            dt = 0.0  # les étapes instantanées suivantes s'enchaînent dans le même pas

    def stop(self) -> None:
        if not self.finished:
            self.run.results[self.index].status = StepStatus.FAILED
            self.run.results[self.index].detail = "Interrompu par l'opérateur"
            self._abort()

    def run_headless(self, dt: float = 0.02, max_time_s: float = 600.0) -> ScenarioRun:
        self.tick(0.0)
        while not self.finished and self.run.sim_time_s < max_time_s:
            self.rt.step(dt)
            self.tick(dt)
        return self.run

    # ------------------------------------------------------------------
    def _advance(self, step: Step, result: StepResult) -> bool:
        p = step.params
        if step.kind == "say":
            self.narration = p["say"]
            result.status = StepStatus.PASSED
            return True
        if step.kind == "action":
            self._do(p)
            result.status = StepStatus.PASSED
            return True
        if step.kind == "wait":
            if self.elapsed + 1e-9 >= float(p["wait"]):
                result.status = StepStatus.PASSED
                return True
            return False
        if step.kind == "wait_until":
            return self._poll(p["wait_until"], float(p["timeout"]), result, "Condition atteinte")
        # expect
        cond = p["expect"]
        if "during" in p:
            ok, observed = self.evaluate(cond)
            if not ok:
                return self._fail(result, f"Condition perdue après {self.elapsed:.2f} s ({observed})")
            if self.elapsed + 1e-9 >= float(p["during"]):
                result.status, result.detail = StepStatus.PASSED, f"Tenue pendant {p['during']} s"
                return True
            return False
        return self._poll(cond, float(p.get("within", 0.0)), result, "Vérifié")

    def _poll(self, cond: dict, timeout: float, result: StepResult, ok_text: str) -> bool:
        ok, observed = self.evaluate(cond)
        if ok:
            result.status = StepStatus.PASSED
            result.detail = f"{ok_text} en {self.elapsed:.2f} s" if self.elapsed > 0 else ok_text
            return True
        if self.elapsed + 1e-9 >= timeout:
            limit = f" après {timeout} s" if timeout else ""
            return self._fail(result, f"Non vérifié{limit} : {observed}")
        return False

    @staticmethod
    def _fail(result: StepResult, detail: str) -> bool:
        result.status, result.detail = StepStatus.FAILED, detail
        return True

    def _abort(self) -> None:
        for r in self.run.results:
            if r.status in (StepStatus.PENDING, StepStatus.RUNNING):
                r.status = StepStatus.SKIPPED
        inputs = self.rt.vehicle.inputs
        inputs.accelerator, inputs.brake = 0.0, 0.6  # mise en sécurité du véhicule
        self.finished = True
        step = self.run.failed_step
        self.narration = (f"Échec à l'étape {step + 1} : {self.scenario.steps[step].label}"
                          if step is not None else "Scénario interrompu")

    def _do(self, p: dict) -> None:
        v, inputs, action = self.rt.vehicle, self.rt.vehicle.inputs, p["action"]
        if action == "power_on":
            v.power_on()
        elif action == "power_off":
            v.power_off()
        elif action == "gear":
            inputs.requested_gear = p["value"]
        elif action == "accelerator":
            inputs.accelerator, inputs.brake = float(p["value"]), 0.0
        elif action == "brake":
            inputs.accelerator, inputs.brake = 0.0, float(p["value"])
        elif action == "release":
            inputs.accelerator, inputs.brake = 0.0, 0.0
        elif action == "input":
            for name, value in p["values"].items():
                setattr(inputs, name, value)
        elif action == "soc":
            v.soc_pct = float(p["value"])
        elif action == "battery_temp":
            v.battery_temp_c = float(p["value"])
        elif action == "mute":
            v.muted.add(p["message"])
        elif action == "unmute":
            v.muted.discard(p["message"])
        elif action == "corrupt":
            v.corrupted.add(p["message"])
        elif action == "repair":
            v.corrupted.discard(p["message"])

    # ------------------------------------------------------------------
    def evaluate(self, cond: dict) -> tuple[bool, str]:
        """Retourne (condition vraie ?, valeur observée lisible)."""
        s = self.rt.state
        key, expected = next(iter(cond.items()))
        alerts = ", ".join(a.code for a in s.alerts) or "aucune alerte"
        if key == "alert":
            return s.has_alert(expected), alerts
        if key == "no_alert":
            return not s.has_alert(expected), alerts
        if key == "no_critical":
            return not any(a.level == "critical" for a in s.alerts), alerts
        if key == "valid":
            return s.is_valid(expected), "valide" if s.is_valid(expected) else "invalide"
        if key == "invalid":
            return not s.is_valid(expected), "valide" if s.is_valid(expected) else "invalide"
        if key == "rejected":
            rejection = self.rt.vehicle.last_rejection
            return bool(rejection) == bool(expected), rejection or "aucun refus"
        value = getattr(s, key)
        shown = f"{key} = {value:.1f}" if isinstance(value, float) else f"{key} = {value}"
        if isinstance(expected, list):
            op, target = expected
            return OPERATORS[op](value, target), shown
        return value == expected, shown
