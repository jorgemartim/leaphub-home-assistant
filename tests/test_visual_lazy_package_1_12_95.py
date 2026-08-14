from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from leapmotor_api.image import CarImagePackage

ROOT = Path(__file__).resolve().parents[1]
CONNECTOR_PATH = ROOT / "leaphub_gateway" / "connector.py"

def load_connector():
    spec = importlib.util.spec_from_file_location("leaphub_connector_195_test", CONNECTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def png_layer(size, rgba, box=None):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(box or (0, 0, size[0] - 1, size[1] - 1), fill=rgba)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

def gradient_body(size):
    image = Image.new("RGBA", size)
    pixels = image.load()
    for y in range(size[1]):
        for x in range(size[0]):
            pixels[x, y] = ((x * 7 + y * 3) % 256, (x * 5 + y * 11) % 256, (x * 13 + y * 2) % 256, 255)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()

def sample_zip():
    size = (160, 90)
    layers = {
        "carpic_body.png": gradient_body(size),
        "carpic_rightbehind_close.png": png_layer(size, (0, 0, 0, 0)),
        "carpic_rightfront_close.png": png_layer(size, (0, 0, 0, 0)),
        "carpic_hood_close.png": png_layer(size, (0, 0, 0, 0)),
        "carpic_leftbehind_close.png": png_layer(size, (0, 0, 0, 0)),
        "carpic_leftfront_close.png": png_layer(size, (0, 0, 0, 0)),
        "carpic_leftbehind_window_close.png": png_layer(size, (100, 150, 220, 80), (20, 20, 70, 55)),
        "carpic_leftfront_window_close.png": png_layer(size, (120, 170, 230, 90), (72, 18, 125, 55)),
        "carpic_leftfront_open.png": png_layer(size, (210, 30, 30, 220), (70, 10, 150, 80)),
        "carpic_tailgate_open.png": png_layer(size, (40, 220, 40, 220), (110, 5, 158, 40)),
        "carpic_charge_open.png": png_layer(size, (80, 160, 250, 120), (0, 60, 45, 89)),
    }
    for i in range(2, 16):
        layers[f"carpic_charge{i}.png"] = png_layer(size, (30 + i, 120, 240, 100), (5 + i, 70, 40 + i, 88))
    for i in range(30):
        layers[f"unused_{i:02d}.png"] = png_layer(size, (i, i, i, 10))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, raw in layers.items():
            archive.writestr(name, raw)
    return out.getvalue()

def test_lazy_package_starts_empty_and_matches_upstream_pixels():
    connector = load_connector()
    raw = sample_zip()
    lazy = connector._LazyOfficialImagePackage.from_zip(raw)
    eager = CarImagePackage.from_zip(raw)
    assert lazy.decoded_layer_count == 0
    stack = [
        "carpic_rightbehind_close.png", "carpic_rightfront_close.png",
        "carpic_body.png", "carpic_hood_close.png", "carpic_leftbehind_close.png",
        "carpic_leftfront_open.png", "carpic_leftbehind_window_close.png",
    ]
    lazy_canvas = lazy._composite_layers(stack)
    eager_canvas = eager._composite_layers(stack)
    assert lazy_canvas.size == eager_canvas.size
    assert lazy_canvas.tobytes() == eager_canvas.tobytes()
    assert 1 <= lazy.decoded_layer_count <= len(set(stack))
    assert lazy.decoded_layer_count < len(lazy.layer_names)

def test_fast_lossless_webp_roundtrip_preserves_pixels():
    connector = load_connector()
    lazy = connector._LazyOfficialImagePackage.from_zip(sample_zip())
    canvas = lazy._composite_layers(["carpic_body.png", "carpic_leftfront_open.png"])
    png = lazy._export(canvas, "PNG")
    encoded, metadata = connector._encode_official_composite(png, "image/png")
    with Image.open(io.BytesIO(encoded)) as decoded:
        decoded_rgba = decoded.convert("RGBA")
    assert decoded_rgba.size == canvas.size
    assert decoded_rgba.tobytes() == canvas.tobytes()
    assert metadata["format"] == "webp-lossless-rgba-official"
    assert metadata["official_canvas_preserved"] is True

def test_lazy_charging_animation_stays_animated_and_lazy():
    connector = load_connector()
    lazy = connector._LazyOfficialImagePackage.from_zip(sample_zip())
    status = connector._official_visual_status(["charging"], "charging")
    animated, mime = lazy.compose_animated(status, frame_duration=80)
    assert mime == "image/webp"
    with Image.open(io.BytesIO(animated)) as image:
        assert bool(getattr(image, "is_animated", False))
        assert int(getattr(image, "n_frames", 1)) == 14
    assert lazy.decoded_layer_count < len(lazy.layer_names)
