from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8')
CONFIG = yaml.safe_load((ROOT / 'leaphub_gateway/config.yaml').read_text(encoding='utf-8'))
CHANGELOG = (ROOT / 'leaphub_gateway/CHANGELOG.md').read_text(encoding='utf-8')
TARGET = (ROOT / 'leaphub_gateway/RELEASE_TARGET').read_text(encoding='utf-8').strip()


# 1.12.77 — estes tres carimbavam versao literal e reprovavam a cada release,
# dentro da copia PROMOVIDA da validacao. A garantia real e a publicacao em duas
# fases: o config nunca passa do RELEASE_TARGET, e o changelog descreve o alvo.
def _tupla(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().strip('"').split('.'))


checks = {
    'version': _tupla(str(CONFIG.get('version'))) <= _tupla(TARGET),
    'prebuilt_image': CONFIG.get('image') == 'ghcr.io/jorgemartim/leaphub-gateway',
    'amd64_only': CONFIG.get('arch') == ['amd64'],
    'single_build_job': 'Build image first, publish App version last' in BUILD and 'matrix:' not in BUILD,
    'runtime_test_dependencies': '"pytest>=8,<10"' in BUILD and '-r leaphub_gateway/requirements.txt' in BUILD,
    'buildx_cache': 'cache-from: type=gha' in BUILD and 'cache-to: type=gha' in BUILD,
    'exact_tag_smoke_test': 'Smoke test exact published image' in BUILD and 'steps.app.outputs.image' in BUILD,
    'anonymous_check_blocks_promotion': 'continue-on-error: true' not in BUILD and 'Verify anonymous GHCR access before exposing update to Home Assistant' in BUILD and 'Promote App metadata only after image is public' in BUILD,
    'source_label': 'org.opencontainers.image.source=https://github.com/jorgemartim/leaphub-home-assistant' in BUILD,
    'release_summary': 'GITHUB_STEP_SUMMARY' in BUILD,
    'single_changelog_heading': re.findall(r'^##\s+(.+)$', CHANGELOG, flags=re.MULTILINE) == [TARGET],
}
failed=[name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f'failed: {failed}')
print({'ok': True, 'checks': len(checks), 'version': TARGET})
