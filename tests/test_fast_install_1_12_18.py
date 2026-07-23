from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
assert config["version"] == "1.12.23"
assert not config.get("image")
assert (APP / "Dockerfile").is_file()
assert "/data/runtime/bin/cloudflared rix," in (APP / "apparmor.txt").read_text(encoding="utf-8")
assert len(config.get("options", {})) == 47

dockerfile = (APP / "Dockerfile").read_text(encoding="utf-8")
assert "cloudflared/releases/download" not in dockerfile
assert "curl --fail" not in dockerfile
assert "ca-certificates libstdc++6" in dockerfile

manager = (APP / "gateway_manager.py").read_text(encoding="utf-8")
for marker in (
    'VERSION = "1.12.23"',
    "def resolve_cloudflared()",
    "CLOUDFLARED_SHA256_AMD64",
    "MAX_CLOUDFLARED_BYTES",
    "os.replace(temp, target)",
    'if not bool(OPTIONS.get("tunnel_enabled", False))',
):
    assert marker in manager, marker

workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
for marker in (
    "docker/setup-buildx-action@v3",
    "--cache-from type=gha",
    "--cache-to type=gha",
    "Smoke-test exact runtime image",
    "docker buildx imagetools inspect",
    "Manifesto publicado",
):
    assert marker in workflow, marker

# O schema atual e o catálogo de comandos não podem perder recursos nesta otimização.
schema_keys = set(config.get("schema", {}))
assert schema_keys == set(config.get("options", {}))
ocpp = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
for command_marker in ("RemoteStartTransaction", "RemoteStopTransaction", "UnlockConnector", "ChangeAvailability"):
    assert command_marker in ocpp, command_marker
assert (ROOT / "tests" / "test_remote_command_matrix.py").is_file()
print("recovery local build 1.12.23 contract ok")
