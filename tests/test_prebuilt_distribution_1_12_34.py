from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILD = (ROOT / '.github/workflows/build.yml').read_text(encoding='utf-8')
CONFIG = yaml.safe_load((ROOT / 'leaphub_gateway/config.yaml').read_text(encoding='utf-8'))
CHANGELOG = (ROOT / 'leaphub_gateway/CHANGELOG.md').read_text(encoding='utf-8')

checks = {
    'version': CONFIG.get('version') == '1.12.34',
    'prebuilt_image': CONFIG.get('image') == 'ghcr.io/jorgemartim/leaphub-gateway',
    'amd64_only': CONFIG.get('arch') == ['amd64'],
    'single_build_job': 'Validate, build and publish amd64 image' in BUILD and 'matrix:' not in BUILD,
    'no_runtime_pytest_before_image': 'pytest' not in BUILD,
    'buildx_cache': 'cache-from: type=gha' in BUILD and 'cache-to: type=gha' in BUILD,
    'exact_tag_smoke_test': 'Smoke test exact published image' in BUILD and 'steps.app.outputs.image' in BUILD,
    'anonymous_check_non_blocking': 'continue-on-error: true' in BUILD and 'Verify anonymous image access for Home Assistant' in BUILD,
    'source_label': 'org.opencontainers.image.source=https://github.com/jorgemartim/leaphub-home-assistant' in BUILD,
    'release_summary': 'GITHUB_STEP_SUMMARY' in BUILD,
    'single_changelog_heading': re.findall(r'^##\s+(.+)$', CHANGELOG, flags=re.MULTILINE) == ['1.12.34'],
}
failed=[name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(f'failed: {failed}')
print({'ok': True, 'checks': len(checks), 'version': '1.12.34'})
