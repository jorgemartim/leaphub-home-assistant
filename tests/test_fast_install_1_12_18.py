from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
# 1.12.74 — lido do alvo em vez de escrito a mao. O par {anterior, atual} era
# reescrito a cada release e nao sobrevive a uma substituicao geral de versao:
# ela colapsa as duas pontas no mesmo numero e apaga a tolerancia que existe
# para a publicacao em duas fases (o config.yaml so e promovido depois de a
# imagem ficar publica no GHCR).
TARGET = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
assert tuple(int(p) for p in str(config["version"]).split(".")) <= tuple(
    int(p) for p in TARGET.split(".")
), "o config.yaml anuncia uma versao maior que o alvo"
assert config.get("image") == "ghcr.io/jorgemartim/leaphub-gateway"
assert (APP / "Dockerfile").is_file()
assert "/data/runtime/bin/cloudflared rix," in (APP / "apparmor.txt").read_text(encoding="utf-8")
assert len(config.get("options", {})) == 48

dockerfile = (APP / "Dockerfile").read_text(encoding="utf-8")
assert "cloudflared/releases/download" not in dockerfile
assert "curl --fail" not in dockerfile
assert "ca-certificates libstdc++6" in dockerfile

manager = (APP / "gateway_manager.py").read_text(encoding="utf-8")
for marker in (
    'VERSION = "1.12.74"',
    "def resolve_cloudflared()",
    "CLOUDFLARED_SHA256_AMD64",
    "MAX_CLOUDFLARED_BYTES",
    "os.replace(temp, target)",
    'if not bool(OPTIONS.get("tunnel_enabled", False))',
):
    assert marker in manager, marker

workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
for marker in (
    "docker/setup-buildx-action@v4",
    "cache-from: type=gha",
    "cache-to: type=gha",
    "Smoke test exact published image",
    "docker buildx imagetools inspect",
    "Verify anonymous GHCR access before exposing update to Home Assistant",
):
    assert marker in workflow, marker

# O schema atual e o catálogo de comandos não podem perder recursos nesta otimização.
schema_keys = set(config.get("schema", {}))
assert schema_keys == set(config.get("options", {}))
ocpp = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
for command_marker in ("RemoteStartTransaction", "RemoteStopTransaction", "UnlockConnector", "ChangeAvailability"):
    assert command_marker in ocpp, command_marker
assert (ROOT / "tests" / "test_remote_command_matrix.py").is_file()
print("fast prebuilt install current contract ok")
