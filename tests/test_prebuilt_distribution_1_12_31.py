from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
assert config["version"] in {"1.12.48", "1.12.68"}
assert config["image"] == "ghcr.io/jorgemartim/leaphub-gateway"
assert config["arch"] == ["amd64"]

changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
headings = re.findall(r"^##\s+(.+)$", changelog, flags=re.MULTILINE)
assert headings == ["1.12.68"], headings
assert "pré-compilada" in changelog

workflow = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
for action in (
    "actions/checkout@v6",
    "docker/setup-buildx-action@v4",
    "docker/login-action@v4",
    "docker/build-push-action@v7",
):
    assert action in workflow, action
assert "actions/checkout@v7" not in workflow
assert "docker/login-action@v4.4.0" not in workflow
for marker in (
    "ghcr.io/jorgemartim/leaphub-gateway",
    "cache-from: type=gha",
    "cache-to: type=gha,mode=max",
    "Smoke test exact published image",
    "Verify anonymous GHCR access before exposing update to Home Assistant",
    "docker logout",
):
    assert marker in workflow, marker

# The Home Assistant release surface is current-only; historical markdown files may remain as source archive.
assert (ROOT / "RELEASE-1.12.68.md").is_file()
assert (APP / "RELEASE-1.12.68.md").is_file()

# Heavy dependencies remain in a stable Docker layer before application code.
dockerfile = (APP / "Dockerfile").read_text(encoding="utf-8")
requirements_pos = dockerfile.index("COPY requirements.txt")
pip_pos = dockerfile.index("pip install --requirement")
source_pos = dockerfile.index("COPY connector.py")
assert requirements_pos < pip_pos < source_pos

print({"ok": True, "version": config["version"], "image": config["image"], "release_headings": headings})
