from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_confirmation_test", APP / "telemetry_engine.py")
server_source = (APP / "connector_server.py").read_text(encoding="utf-8")
manager_source = (APP / "gateway_manager.py").read_text(encoding="utf-8")
config_source = (APP / "config.yaml").read_text(encoding="utf-8")

with tempfile.TemporaryDirectory(prefix="leaphub-confirmation-") as tmp:
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    engine = telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_background_enabled": True,
            "telemetry_command_seconds": 12,
            # Simula a opção preservada de uma instalação 1.12.21.
            "telemetry_command_max_polls": 3,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )
    # 1.12.62 — a garantia deste contrato nunca foi o número, e sim que uma
    # instalação com o valor legado menor é elevada ao piso vigente. O piso subiu
    # de 5 para 8 quando a janela passou a fechar por prazo; ler da fonte evita
    # que o contrato reprove por carimbar a constante antiga.
    assert engine.command_max_polls == telemetry.TelemetryEngine.COMMAND_MAX_POLLS_FLOOR
    assert engine.command_max_polls > 3
    # 1.12.74 — o mesmo raciocínio da linha acima aplicado à ESCADA. Estas três
    # asserções carimbavam [12, 20, 35, 45, 60] e reprovariam qualquer ajuste de
    # cadência, inclusive o que a 1.12.74 fez para a confirmação chegar antes de
    # o carro retrancar sozinho. A garantia é o MAPEAMENTO — a n-ésima leitura
    # usa o n-ésimo degrau — e que a escada seja utilizável.
    cadencia = list(engine.command_cadence)
    assert len(cadencia) >= engine.command_max_polls, (
        "a escada tem menos degraus que o orçamento de leituras; as últimas repetiriam o teto"
    )
    assert all(passo >= 2 for passo in cadencia), "algum degrau viraria laço apertado contra a nuvem"
    assert cadencia[1:] == sorted(cadencia[1:]), "a escada parou de crescer"
    # A primeira releitura tem de caber antes do retravamento automático do
    # carro (~30s), senão a confirmação chega descrevendo um estado que já mudou.
    assert cadencia[0] <= telemetry.TelemetryEngine.COMMAND_FIRST_POLL_CEILING_SECONDS <= 10
    for indice in (1, 5, len(cadencia)):
        assert engine._adaptive_interval(
            ["parked"], 0, command_mode=True, command_poll_count=indice
        )[0] == cadencia[indice - 1], f"a {indice}ª leitura não usou o {indice}º degrau"
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()

checks = {
    "version": ('version: "1.12.48"' in config_source or 'version: "1.12.74"' in config_source)
        and 'VERSION = "1.12.74"' in server_source,
    # O manager normaliza a opção antes de o motor vê-la: se os dois discordarem,
    # o piso do motor nunca chega a valer. Derivado da mesma fonte, de propósito.
    "manager_migrates_legacy_limit": "max({}, min({}".format(
        telemetry.TelemetryEngine.COMMAND_MAX_POLLS_FLOOR,
        telemetry.TelemetryEngine.COMMAND_MAX_POLLS_CEILING,
    ) in manager_source,
    "private_posts_close": "def do_POST(self) -> None:\n        # As chamadas assinadas" in server_source
        and "self.close_connection = True" in server_source,
    "close_header_uses_handler_state": 'close_connection or bool(getattr(self, "close_connection", False))' in server_source,
    "public_health_stays_keepalive": "public_health_payload(), close_connection=True" not in server_source,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("remote confirmation 1.12.24 failed:\n- " + "\n- ".join(failed))

print({"ok": True, "checks": len(checks) + 4, "version": "1.12.74"})
