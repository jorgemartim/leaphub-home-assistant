from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
assert config["version"] in {"1.12.47", "1.12.50"}
assert config["image"] == "ghcr.io/jorgemartim/leaphub-gateway"
assert config["arch"] == ["amd64"]

changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
headings = re.findall(r"^##\s+(.+)$", changelog, flags=re.MULTILINE)
assert headings == ["1.12.50"], headings

workflow = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
for marker in (
    "actions/checkout@v6",
    "docker/setup-buildx-action@v4",
    "docker/login-action@v4",
    "docker/build-push-action@v7",
    "Compile Python sources",
    "python3 -m compileall -q leaphub_gateway",
    "provenance: false",
    "Verify anonymous GHCR access before exposing update to Home Assistant",
    "Promote App metadata only after image is public",
    "GITHUB_STEP_SUMMARY",
):
    assert marker in workflow, marker
assert "actions/checkout@v7" not in workflow
assert "docker/login-action@v4.4.0" not in workflow
assert (ROOT / "GITHUB-RECOVERY-1.12.50.md").is_file()
assert (ROOT / "RELEASE-1.12.50.md").is_file()
assert (APP / "RELEASE-1.12.50.md").is_file()
print({"ok": True, "version": config["version"], "release_headings": headings})
