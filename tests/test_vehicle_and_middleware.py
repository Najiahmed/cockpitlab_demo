import pytest

from cockpitlab.app.runtime import CockpitRuntime


@pytest.fixture
def rt():
    runtime = CockpitRuntime()
    yield runtime
    runtime.shutdown()


def drive(rt, seconds, accelerator=1.0):
    rt.vehicle.inputs.accelerator = accelerator
    rt.run_for(seconds)
    rt.vehicle.inputs.accelerator = 0.0


# --- Bus ------------------------------------------------------------------
def test_all_messages_emitted_at_their_cycle(rt):
    rt.run_for(1.0)
    counts: dict[int, int] = {}
    for frame in rt.bus.recent(10_000):
        counts[frame.arbitration_id] = counts.get(frame.arbitration_id, 0) + 1
    assert counts[0x1A0] == pytest.approx(50, abs=1)   # ESP_Speed, 20 ms
    assert counts[0x0C8] == pytest.approx(10, abs=1)   # VCU_Status, 100 ms
    assert counts[0x3B0] == pytest.approx(2, abs=1)    # BMS_Battery, 500 ms


# --- Démarrage et rapports -------------------------------------------------
def test_vehicle_does_not_move_when_not_ready(rt):
    rt.vehicle.inputs.requested_gear = "D"
    drive(rt, 2)
    assert rt.state.speed_kmh == 0
    assert rt.state.gear == "P"
    assert "non démarré" in rt.vehicle.last_rejection


def test_acceleration_0_to_100_is_plausible(rt):
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "D"
    rt.vehicle.inputs.accelerator = 1.0
    t = 0.0
    while rt.state.speed_kmh < 100 and t < 20:
        rt.step(0.02)
        t += 0.02
    assert 6 < t < 12


def test_gear_change_to_reverse_refused_at_speed(rt):
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "D"
    drive(rt, 3)
    rt.vehicle.inputs.requested_gear = "R"
    rt.run_for(0.2)
    assert rt.state.gear == "D"
    assert rt.vehicle.inputs.requested_gear == "D"  # la demande refusée est oubliée


def test_reverse_speed_is_limited(rt):
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "R"
    drive(rt, 10)
    assert rt.state.speed_kmh <= 20.01


def test_braking_stops_the_vehicle(rt):
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "D"
    drive(rt, 5)
    rt.vehicle.inputs.brake = 1.0
    rt.run_for(4)
    assert rt.state.speed_kmh == 0


def test_driving_consumes_battery_and_braking_regenerates(rt):
    rt.vehicle.power_on()
    rt.vehicle.inputs.requested_gear = "D"
    soc_start = rt.vehicle.soc_pct
    rt.vehicle.inputs.accelerator = 1.0
    rt.run_for(5)
    assert rt.state.power_kw > 0
    assert rt.vehicle.soc_pct < soc_start
    rt.vehicle.inputs.accelerator = 0.0
    rt.run_for(0.2)
    assert rt.state.power_kw < 0


# --- Middleware et alertes -------------------------------------------------
def test_low_battery_alert(rt):
    rt.vehicle.soc_pct = 14.0
    rt.run_for(1)
    assert rt.state.has_alert("LOW_BATTERY")


def test_no_low_battery_alert_above_threshold(rt):
    rt.vehicle.soc_pct = 16.0
    rt.run_for(1)
    assert not rt.state.has_alert("LOW_BATTERY")


def test_seatbelt_alert_only_when_moving(rt):
    rt.vehicle.power_on()
    rt.vehicle.inputs.seatbelt_buckled = False
    rt.run_for(1)
    assert not rt.state.has_alert("SEATBELT")
    rt.vehicle.inputs.requested_gear = "D"
    drive(rt, 3)
    assert rt.state.has_alert("SEATBELT")


def test_hazard_lights_both_blinkers(rt):
    rt.vehicle.inputs.hazard = True
    rt.run_for(0.3)
    assert rt.state.left_turn and rt.state.right_turn


def test_lost_frame_raises_signal_lost(rt):
    rt.run_for(1)
    assert rt.state.is_valid("ESP_Speed")
    # Simule un calculateur ESP muet : on retire sa trame de la base d'émission.
    rt.vehicle.database = type(rt.vehicle.database)(
        tuple(m for m in rt.vehicle.database.messages if m.name != "ESP_Speed")
    )
    rt.run_for(0.2)
    assert not rt.state.is_valid("ESP_Speed")
    assert rt.state.has_alert("SIGNAL_LOST:ESP_Speed")


def test_unknown_frames_are_counted_not_crashing(rt):
    rt.bus.send(0x7FF, b"\x00" * 8)
    assert rt.state_service.unknown_frames == 1
