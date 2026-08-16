from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "leaphub_gateway" / "official_trip_probe.py"
spec = importlib.util.spec_from_file_location("official_daily_mapping_11298", PROBE_PATH)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_real_c10_shape_maps_only_allowlisted_daily_values_without_units():
    parsed = {
        "code": 0,
        "result": 1,
        "message": "SECRET MESSAGE MUST NOT BE COPIED",
        "data": {
            "totalAccumulatedMileageMile": "12,345 mi",
            "totalmileageMile": "321 mi",
            "totalAccumulatedMileage": 19867.2,
            "totalmileage": 516.7,
            "deliveryDays": 81,
            "totalEnergy": 4321.25,
            "secretReference": "SECRET-TRIP-ID",
            "detail": [{
                "currentMileage": 19867.2,
                "xDay": 1,
                "accumulatedMileage": 516.7,
                "accumulatedMileageMile": "321 mi",
                "accumulatedEnergyConsume": 88.5,
                "day": "2026-08-15",
                "vin": "LPS12345678901234",
                "token": "SECRET-TOKEN",
            }],
        },
    }
    mapped, fields = probe.map_c10_daily_values(parsed)
    assert mapped is not None
    assert mapped["schema_version"] == 1
    assert mapped["unit_status"] == "unverified"
    assert mapped["totals"] == {
        "total_accumulated_mileage_raw": 19867.2,
        "total_mileage_raw": 516.7,
        "delivery_days": 81,
        "total_energy_raw": 4321.25,
        "total_accumulated_mileage_mile_text": "12,345 mi",
        "total_mileage_mile_text": "321 mi",
    }
    assert mapped["days"] == [{
        "day": "2026-08-15",
        "x_day": 1,
        "current_mileage_raw": 19867.2,
        "accumulated_mileage_raw": 516.7,
        "accumulated_energy_consume_raw": 88.5,
        "accumulated_mileage_mile_text": "321 mi",
    }]
    encoded = json.dumps({"mapped": mapped, "fields": fields}, ensure_ascii=False)
    for forbidden in ("SECRET MESSAGE", "SECRET-TRIP-ID", "LPS12345678901234", "SECRET-TOKEN", "secretReference", '"vin"', '"token"'):
        assert forbidden not in encoded
    assert "data.totalEnergy" in fields and "data.detail[].day" in fields


def test_partial_or_unknown_shape_remains_redacted_and_unmapped():
    mapped, fields = probe.map_c10_daily_values({"data": {"totalEnergy": 123.456, "reference": "SECRET"}})
    assert mapped is None and fields == []
