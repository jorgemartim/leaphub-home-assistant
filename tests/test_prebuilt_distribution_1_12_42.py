from pathlib import Path
import re
import yaml
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'leaphub_gateway'
config = yaml.safe_load((APP / 'config.yaml').read_text(encoding='utf-8'))
target = (APP / 'RELEASE_TARGET').read_text(encoding='utf-8').strip()
build = (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8')
assert target == '1.12.65'
assert config['version'] in {'1.12.48', '1.12.65'}
assert config['image'] == 'ghcr.io/jorgemartim/leaphub-gateway'
assert 'Smoke test exact published image while authenticated' in build
assert 'import gateway_manager' not in build
assert 'find_spec(module)' in build
assert 'timeout 60s docker run' in build
assert 'Verify anonymous GHCR access before exposing update to Home Assistant' in build
assert 'Promote App metadata only after image is public' in build
assert 'continue-on-error: true' not in build
assert (APP / 'RELEASE-1.12.65.md').is_file()
assert re.findall(r'^##\s+(.+)$', (APP / 'CHANGELOG.md').read_text(encoding='utf-8'), re.M) == ['1.12.65']
print({'ok': True, 'version': '1.12.65', 'distribution': 'prebuilt-staged'})
