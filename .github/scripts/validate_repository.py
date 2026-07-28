from __future__ import annotations

import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "leaphub_gateway"


def fail(message: str) -> None:
    print(f"ERRO: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        fail(f"YAML inválido em {path.relative_to(ROOT)}: {exc}")
    if not isinstance(data, dict):
        fail(f"{path.relative_to(ROOT)} precisa conter um objeto YAML.")
    return data


def version_tuple(value: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", value):
        fail(f"Versão inválida: {value}")
    return tuple(int(part) for part in value.split("."))


repository = load_yaml(ROOT / "repository.yaml")
for key in ("name", "url", "maintainer"):
    if not repository.get(key):
        fail(f"repository.yaml não contém {key}.")

config = load_yaml(APP / "config.yaml")
required = ("name", "version", "slug", "description", "arch")
for key in required:
    if not config.get(key):
        fail(f"config.yaml não contém {key}.")

published_version = str(config["version"])
target_file = APP / "RELEASE_TARGET"
target_version = target_file.read_text(encoding="utf-8").strip() if target_file.is_file() else published_version
version_tuple(published_version)
version_tuple(target_version)
if version_tuple(published_version) > version_tuple(target_version):
    fail(f"Versão publicada {published_version} não pode ser maior que o alvo {target_version}.")
staged = published_version != target_version

image = str(config.get("image") or "").strip()
if image != "ghcr.io/jorgemartim/leaphub-gateway":
    fail("A distribuição normal precisa usar a imagem GHCR oficial pré-compilada.")

architectures = set(config["arch"])
if architectures != {"amd64"}:
    fail(f"Arquiteturas inesperadas: {sorted(architectures)}")

options = config.get("options", {})
for key in (
    "staging_secret",
    "production_secret",
    "ocpp_beta_secret",
    "ocpp_production_secret",
    "tunnel_token",
):
    if options.get(key) not in ("", None):
        fail(f"O valor padrão de {key} precisa permanecer vazio.")

for filename in (
    "connector.py",
    "connector_server.py",
    "telemetry_engine.py",
    "ocpp_gateway.py",
    "gateway_manager.py",
    "privacy.py",
):
    path = APP / filename
    py_compile.compile(str(path), doraise=True)
    content = path.read_text(encoding="utf-8")
    if filename != "connector.py" and target_version not in content:
        fail(f"{filename} não contém a versão-alvo {target_version}.")

# Garante que o Connector será incluído e importado com o mesmo nome usado em runtime.
dockerfile = (APP / "Dockerfile").read_text(encoding="utf-8")
server_source = (APP / "connector_server.py").read_text(encoding="utf-8")
for marker in (
    "COPY connector.py telemetry_engine.py privacy.py /app/",
    "leaphub_connector.py",
    "leaphub_telemetry_engine.py",
    "leaphub_privacy.py",
    "Autoteste de importação de Connector e telemetria concluído",
):
    if marker not in dockerfile:
        fail(f"Dockerfile não contém a proteção obrigatória: {marker}")
if "import leaphub_connector as connector" not in server_source:
    fail("connector_server.py não usa o módulo interno leaphub_connector.")
if "leaphub_telemetry_engine" not in server_source:
    fail("connector_server.py não usa o módulo interno leaphub_telemetry_engine.")
for critical in ("connector.py", "telemetry_engine.py"):
    if (APP / critical).stat().st_size < 1000:
        fail(f"{critical} parece vazio ou incompleto.")

telemetry_source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
for marker in (
    "_prepare_storage(probe=True)",
    "PRAGMA journal_mode=DELETE",
    "PRAGMA temp_store=MEMORY",
    "_record_storage_failure",
):
    if marker not in telemetry_source:
        fail(f"telemetry_engine.py não contém a proteção SQLite obrigatória: {marker}")
# 1.12.50 — WAL passa a ser permitido, mas nunca imposto. A regra anterior
# proibia a string inteira porque uma tentativa antiga passou a exigir WAL sem
# saída: em um /data que recusasse o arquivo -shm, a fila ficava inacessível.
# O contrato agora é outro: quem usar WAL precisa manter o caminho DELETE e cair
# nele sozinho, registrando o motivo. O journal deixa de ser uma imposição do
# código e passa a ser uma escolha do volume.
if "PRAGMA journal_mode=WAL" in telemetry_source:
    for guard in (
        "WAL indisponível neste volume",
        'self.storage_journal_mode = "wal"',
        "PRAGMA synchronous=NORMAL",
        "except sqlite3.OperationalError as exc:",
    ):
        if guard not in telemetry_source:
            fail(
                "telemetry_engine.py usa WAL sem a proteção obrigatória de fallback "
                f"para DELETE: {guard}"
            )

for required_file in (
    "README.md",
    "DOCS.md",
    "CHANGELOG.md",
    "MIGRATION.md",
    "SECURITY.md",
    "Dockerfile",
    "apparmor.txt",
    "icon.png",
    "logo.png",
    "translations/en.yaml",
    "translations/pt-BR.yaml",
):
    if not (APP / required_file).is_file():
        fail(f"Arquivo obrigatório ausente: leaphub_gateway/{required_file}")

for translation in (APP / "translations").glob("*.yaml"):
    load_yaml(translation)

changelog = (APP / "CHANGELOG.md").read_text(encoding="utf-8")
headings = re.findall(r"^##\s+(.+)$", changelog, flags=re.MULTILINE)
if headings != [target_version]:
    fail(f"CHANGELOG.md deve conter somente o release-alvo {target_version}; encontrado: {headings}.")

build_workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
for marker in (
    "RELEASE_TARGET",
    "Verify anonymous GHCR access before exposing update to Home Assistant",
    "Promote App metadata only after image is public",
    "contents: write",
    "[gateway-published]",
):
    if marker not in build_workflow:
        fail(f"build.yml não contém a trava de publicação obrigatória: {marker}")
if "continue-on-error: true" in build_workflow:
    fail("A verificação anônima do GHCR não pode continuar em caso de erro.")

# Os contratos históricos esperam que config.yaml já anuncie a versão de runtime.
# Durante uma publicação em duas fases, validamos os mesmos contratos em uma cópia
# efêmera com apenas esse campo promovido. O repositório real continua anunciando
# a versão anterior até a imagem GHCR ser pública.
test_root = ROOT
cleanup: tempfile.TemporaryDirectory[str] | None = None
if staged:
    cleanup = tempfile.TemporaryDirectory(prefix="leaphub-staged-")
    test_root = Path(cleanup.name) / "repo"
    shutil.copytree(
        ROOT,
        test_root,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )
    staged_config = test_root / "leaphub_gateway" / "config.yaml"
    source = staged_config.read_text(encoding="utf-8")
    source, count = re.subn(
        r'^version:\s*"[^"]+"\s*$',
        f'version: "{target_version}"',
        source,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        fail("Não foi possível promover config.yaml na cópia de validação.")
    staged_config.write_text(source, encoding="utf-8")

try:
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=test_root, check=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "leaphub_gateway/tests"], cwd=test_root, check=True)
finally:
    if cleanup is not None:
        cleanup.cleanup()

mode = "staged; imagem ainda não anunciada" if staged else "publicado"
print(f"Repositório válido. Gateway alvo {target_version}; App {published_version} ({mode}).")
