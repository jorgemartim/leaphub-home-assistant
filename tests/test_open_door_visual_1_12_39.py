from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "open_door_visual_test",
    ROOT / "leaphub_gateway" / "connector.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _PicturePackage:
    def __init__(self) -> None:
        self.base = Image.new("RGBA", (300, 160), (0, 0, 0, 0))
        base_draw = ImageDraw.Draw(self.base)
        base_draw.rectangle((30, 45, 245, 130), fill=(225, 225, 225, 255))
        base_draw.rectangle((150, 42, 235, 100), fill=(70, 75, 82, 255))

        self.open_layer = Image.new("RGBA", self.base.size, (0, 0, 0, 0))
        door_draw = ImageDraw.Draw(self.open_layer)
        door_draw.polygon(
            [(165, 86), (185, 18), (268, 14), (267, 139), (168, 139)],
            fill=(232, 232, 232, 255),
        )
        door_draw.polygon(
            [(166, 86), (185, 18), (268, 14), (267, 85)],
            fill=(55, 60, 66, 230),
        )
        door_draw.ellipse((145, 75, 177, 93), fill=(30, 30, 30, 255))

    def compose(self, status, **_options):
        frame = self.base.copy()
        if status.doors.lbcm_driver_door_status:
            frame.alpha_composite(self.open_layer)
        output = io.BytesIO()
        frame.save(output, format="PNG")
        return output.getvalue()


def test_embedded_open_door_glass_is_rebuilt_from_base() -> None:
    package = _PicturePackage()
    status = SimpleNamespace(doors=SimpleNamespace(lbcm_driver_door_status=True))
    raw, restored_pixels = MODULE._compose_official_frame(package, status)
    cleaned = Image.open(io.BytesIO(raw)).convert("RGBA")
    base = package.base

    assert restored_pixels > 500
    assert cleaned.getpixel((225, 55)) == base.getpixel((225, 55))
    assert cleaned.getpixel((225, 120)) != base.getpixel((225, 120))
    assert cleaned.getpixel((158, 84)) != base.getpixel((158, 84))


def test_closed_door_frame_is_byte_preserved() -> None:
    package = _PicturePackage()
    status = SimpleNamespace(doors=SimpleNamespace(lbcm_driver_door_status=False))
    expected = package.compose(status, format="PNG")
    actual, restored_pixels = MODULE._compose_official_frame(package, status)
    assert restored_pixels == 0
    assert actual == expected
