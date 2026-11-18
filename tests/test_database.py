import pytest

from cockpitlab.bus import DATABASE, Message, Signal


def test_roundtrip_all_messages():
    sample = {
        "ESP_Speed": {"speed_kmh": 87.35},
        "VCU_Status": {"gear": "D", "ready": True, "power_kw": -12.4},
        "BMS_Battery": {"soc_pct": 54.3, "range_km": 168, "battery_temp_c": 27},
        "BCM_Lights": {"left_turn": True, "right_turn": False, "hazard": False,
                       "low_beam": True, "high_beam": False},
        "ACU_Seatbelt": {"seatbelt_buckled": False},
    }
    for name, values in sample.items():
        message = DATABASE.by_name(name)
        decoded = message.decode(message.encode(values))
        for key, value in values.items():
            assert decoded[key] == pytest.approx(value, abs=0.1), (name, key)


def test_values_are_clamped_to_signal_range():
    message = DATABASE.by_name("ESP_Speed")
    assert message.decode(message.encode({"speed_kmh": 9999}))["speed_kmh"] == pytest.approx(655.35)
    assert message.decode(message.encode({"speed_kmh": -5}))["speed_kmh"] == 0


def test_unknown_enum_value_is_rejected():
    with pytest.raises(ValueError):
        DATABASE.by_name("VCU_Status").encode({"gear": "X", "ready": True, "power_kw": 0})


def test_missing_signal_is_rejected():
    with pytest.raises(KeyError):
        DATABASE.by_name("VCU_Status").encode({"gear": "D"})


def test_signals_do_not_overlap():
    for message in DATABASE.messages:
        used: set[int] = set()
        for signal in message.signals:
            bits = set(range(signal.start_bit, signal.start_bit + signal.length))
            assert not bits & used, f"{message.name}.{signal.name} chevauche un autre signal"
            assert max(bits) < message.dlc * 8
            used |= bits


def test_timeout_is_three_cycles():
    msg = Message("X", 0x1, 100, signals=(Signal("a", 0, 1),))
    assert msg.timeout_s == pytest.approx(0.3)
