from __future__ import annotations

import py_compile
import re
import subprocess
import sys
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


repository = load_yaml(ROOT / "repository.yaml")
for key in ("name", "url", "maintainer"):
    if not repository.get(key):
        fail(f"repository.yaml não contém {key}.")

config = load_yaml(APP / "config.yaml")
required = ("name", "version", "slug", "description", "arch")
for key in required:
    if not config.get(key):
        fail(f"config.yaml não contém {key}.")

version = str(config["version"])
if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", version):
    fail(f"Versão inválida: {version}")

image = str(config.get("image") or "").strip()
if image and image != "ghcr.io/jorgemartim/leaphub-gateway":
    fail("A imagem do config.yaml não aponta para o GHCR oficial.")
if not image and not (APP / "Dockerfile").is_file():
    fail("Build local exige Dockerfile quando config.yaml não contém image.")

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
    if filename != "connector.py" and version not in content:
        fail(f"{filename} não contém a versão {version}.")


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
if "PRAGMA journal_mode=WAL" in telemetry_source:
    fail("telemetry_engine.py voltou a forçar WAL, incompatível com o armazenamento protegido do App.")

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
if f"## {version}" not in changelog:
    fail(f"CHANGELOG.md não contém a versão {version}.")

for test_file in (
    ROOT / "tests" / "test_contracts.py",
    ROOT / "tests" / "test_remote_command_matrix.py",
    ROOT / "tests" / "test_comfort_contract.py",
    ROOT / "tests" / "test_auth_recovery_contract.py",
    ROOT / "tests" / "test_gateway_1_12_14.py",
    ROOT / "tests" / "test_resilience_1_12_14.py",
    ROOT / "tests" / "test_connection_resilience_1_12_15.py",
    ROOT / "tests" / "test_full_resilience_1_12_16.py",
    ROOT / "tests" / "test_single_ocpp_1_12_17.py",
    ROOT / "tests" / "test_fast_install_1_12_18.py",
    ROOT / "tests" / "test_background_telemetry_1_12_19.py",
):
    subprocess.run([sys.executable, str(test_file)], cwd=ROOT, check=True)

print(f"Repositório válido. Leap Hub Gateway {version}.")
