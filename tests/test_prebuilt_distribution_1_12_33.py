from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]

# 1.12.77 — este arquivo carimbava a versao literal em cinco lugares e reprovava
# a cada release. As garantias reais: o config nunca passa do RELEASE_TARGET
# (publicacao em duas fases) e os artefatos descrevem o ALVO, seja ele qual for.
_ALVO = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def _tupla_versao(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in str(v).strip().strip('"').strip("'").split("."))


APP = ROOT / "leaphub_gateway"
config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
assert _tupla_versao(config["version"]) <= _tupla_versao(_ALVO)
assert config["image"] == "ghcr.io/jorgemartim/leaphub-gateway"
assert config["arch"] == ["amd64"]

changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
headings = re.findall(r"^##\s+(.+)$", changelog, flags=re.MULTILINE)
assert headings == [_ALVO], headings

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
assert (ROOT / f"GITHUB-RECOVERY-{_ALVO}.md").is_file()
assert (ROOT / f"RELEASE-{_ALVO}.md").is_file()
assert (APP / f"RELEASE-{_ALVO}.md").is_file()
print({"ok": True, "version": config["version"], "release_headings": headings})
