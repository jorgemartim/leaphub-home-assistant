from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
sys.path.insert(0, str(APP))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load("leaphub_connector_visual_112101", APP / "connector.py")


def test_rear_left_closed_glass_layer_is_present():
    stack = connector.official_layer_stack(left_rear_door_open=False, left_rear_window_closed=True)
    assert "carpic_leftbehind_window_close.png" in stack


def test_rear_left_open_glass_layer_is_omitted():
    stack = connector.official_layer_stack(left_rear_door_open=False, left_rear_window_closed=False)
    assert "carpic_leftbehind_window_close.png" not in stack


def test_visual_signature_can_publish_all_four_window_tags():
    doors = {
        "front_left": False,
        "front_right": False,
        "rear_left": False,
        "rear_right": False,
        "trunk": False,
    }
    windows = {
        "front_left": True,
        "front_right": True,
        "rear_left": True,
        "rear_right": True,
    }
    components, signature = connector.build_visual_signature(
        "parked", doors, windows, None, None, {}, {}, {}, {}, {}
    )
    expected = {
        "window-front-left-open",
        "window-front-right-open",
        "window-rear-left-open",
        "window-rear-right-open",
    }
    assert expected.issubset(set(components))
    assert all(item in signature for item in expected)


def test_official_renderer_supports_rear_left_window_component():
    assert "window-rear-left-open" in connector._OFFICIAL_RENDER_COMPONENTS
