from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")

# 1.12.76 — o par de versões literais aqui colapsou num deslize de release e
# reprovava com o config legitimamente atrás do alvo (fase 1 da publicação em
# duas fases). Derivado da fonte: o config nunca pode passar do RELEASE_TARGET.
def _config_nao_passa_do_alvo() -> bool:
    def _t(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in v.strip().strip('"').split("."))
    alvo = _t((ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8"))
    cfg = _t(next(
        l.split(":", 1)[1] for l in (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8").splitlines()
        if l.startswith("version:")
    ))
    return cfg <= alvo


checks = {
    "version": _config_nao_passa_do_alvo() and 'VERSION = "1.12.76"' in SERVER,
    "optional_close_argument": "close_connection: bool = False" in SERVER,
    "close_header": 'self.send_header("Connection", "close")' in SERVER,
    "public_health_keeps_alive": "public_health_payload(), close_connection=True" not in SERVER,
    "details_close": "details, close_connection=True" in SERVER,
    "telemetry_close": "TELEMETRY.status(), close_connection=True" in SERVER,
    "accepted_command_pending": "elif command_dispatched or cloud_accepted:" in CONNECTOR
        and "confirmation_pending = True" in CONNECTOR,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("status delivery 1.12.24 failed:\n- " + "\n- ".join(failed))

print({"ok": True, "checks": len(checks), "version": "1.12.76"})
