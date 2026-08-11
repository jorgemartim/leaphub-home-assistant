from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")
# 1.12.74 — o alvo passou a ser LIDO. Este par {anterior, atual} era escrito a
# mao a cada release e ja colapsou nas duas pontas uma vez, quando uma
# substituicao geral trocou os dois numeros e matou a tolerancia que existe
# justamente para a publicacao em duas fases. O que o contrato quer dizer e "o
# runtime anuncia o alvo, e o config so pode estar nele ou atras dele".
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def _tupla(valor: str) -> tuple[int, ...]:
    return tuple(int(parte) for parte in valor.split("."))


CONFIG_VERSION = ""
for linha in CONFIG.splitlines():
    if linha.startswith("version:"):
        CONFIG_VERSION = linha.split(":", 1)[1].strip().strip('"').strip("'")
        break

checks = {
    # config.yaml so e promovido depois da validacao: o alvo e a versao ainda
    # publicada precisam passar, senao o proprio gate reprova o candidato.
    "version": f'VERSION = "{TARGET}"' in SERVER
        and bool(CONFIG_VERSION)
        and _tupla(CONFIG_VERSION) <= _tupla(TARGET),
    "api_contract": "API_VERSION = 2" in SERVER and 'X-LeapHub-API-Version' in SERVER,
    "trace": 'X-Request-ID' in SERVER and 'trace_id' in SERVER,
    "compatibility": 'incompatible_api' in SERVER,
    "health": 'capability_schema_version' in SERVER,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("contract smoke failed: " + ", ".join(failed))
print({"ok": True, "checks": len(checks)})
