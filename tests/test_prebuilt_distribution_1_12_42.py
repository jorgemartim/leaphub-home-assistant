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


APP = ROOT / 'leaphub_gateway'
config = yaml.safe_load((APP / 'config.yaml').read_text(encoding='utf-8'))
target = (APP / 'RELEASE_TARGET').read_text(encoding='utf-8').strip()
build = (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8')
assert target == '1.12.77'
assert _tupla_versao(config['version']) <= _tupla_versao(_ALVO)
assert config['image'] == 'ghcr.io/jorgemartim/leaphub-gateway'
assert 'Smoke test exact published image while authenticated' in build
assert 'import gateway_manager' not in build
assert 'find_spec(module)' in build
assert 'timeout 60s docker run' in build
assert 'Verify anonymous GHCR access before exposing update to Home Assistant' in build
assert 'Promote App metadata only after image is public' in build
assert 'continue-on-error: true' not in build
assert (APP / f"RELEASE-{_ALVO}.md").is_file()
assert re.findall(r'^##\s+(.+)$', (APP / 'CHANGELOG.md').read_text(encoding='utf-8'), re.M) == [_ALVO]
print({'ok': True, 'version': _ALVO, 'distribution': 'prebuilt-staged'})
