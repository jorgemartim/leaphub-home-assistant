from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def test_release_target_is_runtime_version_and_config_may_be_staged():
    target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
    config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
    assert target == "1.12.57"
    assert config["version"] in {"1.12.48", target}


def test_home_assistant_version_is_promoted_only_after_public_image_check():
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "RELEASE_TARGET" in workflow
    assert "Verify anonymous GHCR access before exposing update to Home Assistant" in workflow
    assert "Promote App metadata only after image is public" in workflow
    assert "continue-on-error: true" not in workflow
    assert workflow.index("Verify anonymous GHCR access") < workflow.index("Promote App metadata only")
    assert "contents: write" in workflow
    assert "[gateway-published]" in workflow
