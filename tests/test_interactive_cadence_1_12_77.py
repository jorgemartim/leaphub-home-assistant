"""1.12.77 — olhar a tela não pode ser mais lento que esperar um comando.

`interactive_seconds` valia 20s (piso 15s) e governa TODOS os estados enquanto
há presença. Medido em campo em 12/08/2026 (conta acct_1c8b987d), o carro
publica uma mudança de trava em ~0-12s:

    lock  confirmado após 1 leitura e  0s
    lock  confirmado após 1 leitura e  1s
    lock  confirmado após 3 leituras e 12s

Com leitura a cada 20s, boa parte da espera que o dono sente é NOSSA. A cortina
não entra nessa conta: o dono confirmou que ela leva 30-40s no próprio
mecanismo, e foi confundindo tempo de mecanismo com latência de telemetria que
o número atravessou tanto tempo sem ser questionado.

Este contrato afirma a GARANTIA, nunca o literal: com a tela aberta, a cadência
não é mais lenta que o primeiro degrau da escada de confirmação de comando — que
já roda em produção sem disparar rate-limit. Ele reprova a 1.12.76.
"""

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


load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_interactive_cadence_test", APP / "telemetry_engine.py")
motor_fonte = (APP / "telemetry_engine.py").read_text(encoding="utf-8")


def _engine(tmp: str, interactive_option: int):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = tmp
    return telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_interactive_seconds": interactive_option,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(2),
    )


def _fechar(engine) -> None:
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


# --- o caso de campo: a opção GRAVADA na instalação -------------------------
# Este é o ponto todo. Uma instalação existente guarda `20` e nunca releria um
# padrão novo; sem teto em código, mudar o default não muda nada no carro do
# dono. É a mesma armadilha de COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS.
with tempfile.TemporaryDirectory(prefix="leaphub-interactive-campo-") as tmp:
    engine = _engine(tmp, 20)
    try:
        primeiro_degrau = engine.command_cadence[0]
        assert engine.interactive_seconds <= primeiro_degrau, (
            f"com a opção de campo (20s) a tela atualiza a cada {engine.interactive_seconds}s, "
            f"mais devagar que o primeiro degrau do comando ({primeiro_degrau}s)"
        )

        # Não é decorativo: o valor tem de CHEGAR na decisão de cadência. Sem
        # esta asserção, a constante poderia existir e nada a consultar.
        for estado in ("parked", "sleep", "charge_watch"):
            intervalo, _rotulo, _streak = engine._adaptive_interval([estado], 0, interactive=True)
            assert intervalo <= primeiro_degrau, (
                f"estado {estado!r} com presença ainda consulta a cada {intervalo}s"
            )

        # --- controle negativo 1: o fundo NÃO acelerou -----------------------
        # Acelerar a telemetria de fundo multiplicaria chamadas o dia inteiro e
        # é justamente o que o rate-limit pune. Só a presença muda de ritmo.
        fundo, _r, _s = engine._adaptive_interval(["parked"], 0, interactive=False)
        assert fundo > engine.interactive_seconds, (
            "a cadência de fundo foi acelerada junto; só a presença deveria mudar"
        )
    finally:
        _fechar(engine)


# --- controle negativo 2: o piso protege contra empilhar chamadas ------------
# O round-trip HTTPS medido em 12/08/2026 ficou entre 2,1s e 4,5s. Um intervalo
# abaixo disso emite chamada sobre chamada sem trazer dado novo: `status/get`
# devolve o último snapshot que o CARRO subiu, não uma leitura ao vivo.
with tempfile.TemporaryDirectory(prefix="leaphub-interactive-piso-") as tmp:
    engine = _engine(tmp, 1)
    try:
        assert engine.interactive_seconds >= 5, (
            f"intervalo de {engine.interactive_seconds}s cai abaixo do round-trip medido (2,1-4,5s)"
        )
    finally:
        _fechar(engine)


# --- controle negativo 3: o teto realmente PRENDE ----------------------------
# Sem o `min(...)`, um valor gravado alto continuaria valendo. Esta é a mutação
# que o contrato precisa matar.
with tempfile.TemporaryDirectory(prefix="leaphub-interactive-teto-") as tmp:
    engine = _engine(tmp, 60)
    try:
        assert engine.interactive_seconds == telemetry.TelemetryEngine.INTERACTIVE_SECONDS_CEILING, (
            f"opção gravada de 60s não foi truncada pelo teto: ficou {engine.interactive_seconds}s"
        )
    finally:
        _fechar(engine)


# --- o teto é o degrau já provado, não um número escolhido -------------------
# Se alguém baixar o teto abaixo do primeiro degrau do comando, estará
# inventando uma cadência sem prova de campo. Ancorar os dois evita isso.
assert (
    telemetry.TelemetryEngine.INTERACTIVE_SECONDS_CEILING
    >= telemetry.TelemetryEngine.COMMAND_FIRST_POLL_CEILING_SECONDS
), "o teto interativo ficou mais agressivo que a cadência de comando provada em produção"
assert "INTERACTIVE_SECONDS_CEILING" in motor_fonte

print("contrato 1.12.77: com a tela aberta a cadência acompanha o degrau do comando")
