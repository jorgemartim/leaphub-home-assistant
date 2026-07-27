from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"
TARGET_FILE = APP / "RELEASE_TARGET"
CONFIG = APP / "config.yaml"
CHECKSUM_FILES = (ROOT / "SOURCE-SHA256SUMS.txt", ROOT / "GITHUB-RECOVERY-SHA256SUMS.txt")
EXCLUDED_NAMES = {"SOURCE-SHA256SUMS.txt", "GITHUB-RECOVERY-SHA256SUMS.txt"}
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache"}


def semver(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", value):
        raise SystemExit(f"Versão inválida: {value!r}")
    return tuple(int(part) for part in value.split("."))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_release_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if path.name in EXCLUDED_NAMES or any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(ROOT).as_posix())


target = TARGET_FILE.read_text(encoding="utf-8").strip()
semver(target)
source = CONFIG.read_text(encoding="utf-8")
match = re.search(r'^version:\s*"([^"]+)"\s*$', source, flags=re.MULTILINE)
if not match:
    raise SystemExit("Não foi possível localizar version em leaphub_gateway/config.yaml")
current = match.group(1)
if semver(current) > semver(target):
    raise SystemExit(f"A versão publicada {current} é maior que o alvo {target}.")

if current != target:
    source = source[: match.start(1)] + target + source[match.end(1) :]
    CONFIG.write_text(source, encoding="utf-8")

lines = [f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}" for path in iter_release_files()]
text = "\n".join(lines) + "\n"
for checksum_file in CHECKSUM_FILES:
    checksum_file.write_text(text, encoding="utf-8")

print(f"Versão publicada promovida: {current} -> {target}")
print(f"Checksums regenerados: {len(lines)} arquivos")
