"""Scénarios : format, exécution, détection des régressions, plausibilité des données."""
import pytest

from cockpitlab.app.runtime import CockpitRuntime
from cockpitlab.builds import BUILDS, REFERENCE_BUILD, get_build
from cockpitlab.scenarios import ScenarioError, ScenarioPlayer, StepStatus, load_scenarios, parse_scenario

SCENARIOS = load_scenarios()


def play(build, scenario):
    return ScenarioPlayer(CockpitRuntime(build=build), scenario).run_headless()


def test_all_scenarios_load():
    assert [s.id for s in SCENARIOS] == [f"SCN-0{i}" for i in range(1, 8)]
    assert all(any(step.is_check for step in s.steps) for s in SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_reference_build_passes_every_scenario(scenario):
    run = play(REFERENCE_BUILD, scenario)
    assert run.passed, (run.failed_step, run.results[run.failed_step or 0].detail)


@pytest.mark.parametrize("version, expected_failures", [
    ("26.11.0-rc1", {"SCN-02", "SCN-04"}),
    ("26.11.0-rc2", {"SCN-03"}),
    ("26.12.0-nightly.142", {"SCN-01", "SCN-02", "SCN-03", "SCN-04", "SCN-07"}),
    ("26.12.0-nightly.143", set()),  # défaut de timing : invisible à l'écran, vu par NR-02
])
def test_scenarios_detect_regressions(version, expected_failures):
    failed = {s.id for s in SCENARIOS if not play(get_build(version), s).passed}
    assert failed == expected_failures


def test_failure_stops_scenario_and_secures_vehicle():
    rt = CockpitRuntime(build=get_build("26.11.0-rc1"))
    player = ScenarioPlayer(rt, SCENARIOS[1])
    run = player.run_headless()
    failed = run.failed_step
    assert run.results[failed].status == StepStatus.FAILED
    assert all(r.status == StepStatus.SKIPPED for r in run.results[failed + 1:])
    assert rt.vehicle.inputs.accelerator == 0 and rt.vehicle.inputs.brake > 0
    assert "Échec" in player.narration


def test_operator_stop():
    rt = CockpitRuntime()
    player = ScenarioPlayer(rt, SCENARIOS[0])
    player.tick(0.0)
    player.stop()
    assert player.finished and not player.run.passed


@pytest.mark.parametrize("step, message", [
    ({"action": "fly"}, "action inconnue"),
    ({"action": "mute", "message": "ABS_X"}, "trame inconnue"),
    ({"wait_until": {"speed_kmh": [">=", 5]}}, "timeout"),
    ({"expect": {"altitude": 3}}, "condition inconnue"),
    ({"expect": {"speed_kmh": ["~", 3]}}, "comparaison"),
    ({"wait": 1, "say": "x"}, "une et une seule"),
])
def test_invalid_scenarios_are_rejected(step, message):
    with pytest.raises(ScenarioError, match=message):
        parse_scenario({"id": "X", "title": "x", "steps": [step]})


# --- Plausibilité et injection de défauts ----------------------------------------
def test_corrupted_speed_is_rejected_then_recovers():
    rt = CockpitRuntime()
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "D"
    rt.vehicle.inputs.accelerator = 0.5
    rt.run_for(4)
    rt.vehicle.corrupted.add("ESP_Speed")
    rt.run_for(1)
    assert rt.state.has_alert("DATA_INVALID:ESP_Speed")
    assert not rt.state.has_alert("SIGNAL_LOST:ESP_Speed")  # la communication, elle, fonctionne
    assert rt.state.speed_kmh < 100
    rt.vehicle.corrupted.clear()
    rt.run_for(0.1)
    assert rt.state.is_valid("ESP_Speed") and not rt.state.alerts


def test_unprotected_frame_corruption_goes_unnoticed():
    """Limite connue : les trames d'états binaires n'ont ni CRC ni compteur (pas d'E2E)."""
    rt = CockpitRuntime()
    rt.vehicle.corrupted.add("BCM_Lights")
    rt.run_for(0.5)
    assert rt.state.high_beam and not rt.state.alerts


def test_build_can_be_installed_hot():
    rt = CockpitRuntime()
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "R"
    rt.vehicle.inputs.accelerator = 1.0
    rt.run_for(10)
    assert rt.state.speed_kmh <= 20.5
    rt.install_build(get_build("26.11.0-rc1"))
    rt.run_for(10)
    assert rt.state.speed_kmh > 30


def test_reset_keeps_the_same_inputs_object():
    rt = CockpitRuntime()
    inputs = rt.vehicle.inputs
    inputs.accelerator = 1.0
    rt.vehicle.muted.add("ESP_Speed")
    rt.vehicle.reset(50)
    assert rt.vehicle.inputs is inputs and inputs.accelerator == 0
    assert not rt.vehicle.muted and rt.vehicle.soc_pct == 50
