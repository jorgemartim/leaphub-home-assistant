from types import SimpleNamespace

from leaphub_gateway import connector


TARGET = "1.12.128"


def test_release_version_is_aligned():
    assert connector.CONNECTOR_VERSION == TARGET


def test_c10_pressure_order_matches_the_official_app():
    # Live official-app sample: FL 228, FR 230, RL 247, RR 244 kPa.
    # leapmotor-api 0.3.2 exposed the same sample in this mixed all_bar order.
    tires = SimpleNamespace(all_bar={
        "front_left": 2.44,
        "front_right": 2.30,
        "rear_left": 2.28,
        "rear_right": 2.47,
    })
    pressures, temperatures = connector.tire_metrics(tires, SimpleNamespace(raw={}), "C10 BEV")
    assert pressures == {
        "front_left": 2.28,
        "front_right": 2.30,
        "rear_left": 2.47,
        "rear_right": 2.44,
    }
    assert temperatures == {}


def test_other_models_keep_the_library_orientation():
    original = {"front_left": 2.31, "front_right": 2.32, "rear_left": 2.41, "rear_right": 2.42}
    pressures, _ = connector.tire_metrics(SimpleNamespace(all_bar=original), SimpleNamespace(raw={}), "B10")
    assert pressures == original


def test_optional_british_temperature_aliases_are_accepted_without_estimation():
    tires = SimpleNamespace(
        all_bar={},
        leftFrontTyreTemperature=31,
        frontRightTyreTemperature=32,
        rearLeftTyreTemperature=33,
        rightRearTyreTemperature=34,
    )
    _, temperatures = connector.tire_metrics(tires, SimpleNamespace(raw={}), "C10")
    assert temperatures == {"front_left": 31.0, "front_right": 32.0, "rear_left": 33.0, "rear_right": 34.0}
