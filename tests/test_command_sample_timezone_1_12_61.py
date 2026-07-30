"""Contrato 1.12.61 — o carimbo da amostra tem fuso, e a confirmação volta a existir.

A confirmação de comando nunca concluía. A 1.12.60 instrumentou o atraso e a
resposta veio da produção em 30/07/2026, num host em -03:00:

    Confirmação inconclusiva de sunshade_open: amostras avaliadas=0,
    descartadas por idade=1, amostra mais recente 10739s antes do comando

Três comandos consecutivos, 2 min entre eles, relataram 10739s, 10740s e 10777s.
Atraso real cresceria com o intervalo; deslocamento fixo não cresce. Era o offset
do fuso: `captured_at` chega **sem fuso** (a `leapmotor_api` faz `strptime`
ingênuo) e o portão de frescura presumia UTC. O site lia o mesmo campo como hora
local e exibia a idade certa — só a comparação da confirmação divergia.

O que este contrato protege:

1. **Amostra sem fuso é lida como hora local.** Se voltar a presumir UTC, todo
   comando volta a ficar inconclusivo num host fora de UTC.
2. **O carimbo sai da origem com fuso.** `iso_timestamp()` anexa o offset local
   ao datetime ingênuo, para nenhum consumidor precisar adivinhar.
3. **Frescura e atraso derivam do mesmo ponto.** Eram dois blocos de parsing
   duplicados; divergir entre eles produziria descarte sem atraso relatado.
4. **Amostra absurdamente no futuro não confirma.** É o guarda contra errar a
   direção do fuso: presumir local um carimbo que fosse mesmo UTC jogaria a
   amostra ~3h à frente, e confirmar com isso seria pior que não confirmar.

Nenhuma asserção fixa a versão exata.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE_SOURCE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
CONNECTOR_SOURCE = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")

# O offset real do host onde o defeito foi medido. O teste não depende de rodar
# em -03:00: ele calcula o offset local e monta o cenário equivalente.
OBSERVED_OFFSET_SECONDS = 10800.0


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"não carregou {path.name}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_engine_class():
    """Carrega a classe do motor.

    `telemetry_engine.py` faz `import leaphub_connector`, que no add-on instalado
    é o `connector.py` copiado para site-packages. Registrar o arquivo sob esse
    nome antes resolve o import — é o mesmo caminho de
    `test_remote_confirmation_1_12_22.py`.
    """
    app = ROOT / "leaphub_gateway"
    if "leaphub_connector" not in sys.modules:
        load_module("leaphub_connector", app / "connector.py")
    module = load_module("leaphub_tz_engine", app / "telemetry_engine.py")
    for value in vars(module).values():
        if hasattr(value, "_command_sample_epoch") and hasattr(value, "_command_sample_is_fresh"):
            return value
    raise AssertionError("classe do motor não encontrada em telemetry_engine.py")


# ------------------------------------------------------------------ estrutural


def test_naive_timestamp_is_not_assumed_utc():
    """A linha que causou o defeito não pode voltar."""
    assert "parsed.replace(tzinfo=timezone.utc)" not in ENGINE_SOURCE, (
        "amostra sem fuso voltou a ser presumida UTC; num host fora de UTC isso "
        "desloca o carimbo pelo offset e descarta 100% das amostras"
    )


def test_timestamp_parsing_lives_in_one_place():
    assert "_command_sample_epoch" in ENGINE_SOURCE
    # Frescura e atraso não podem ter parsing próprio.
    assert ENGINE_SOURCE.count("datetime.fromisoformat(str(raw)") == 1, (
        "o parsing do carimbo foi duplicado outra vez; frescura e atraso precisam "
        "derivar do mesmo ponto para não discordarem"
    )


def test_connector_emits_timestamp_with_offset():
    trecho = CONNECTOR_SOURCE[CONNECTOR_SOURCE.find("def iso_timestamp("):]
    trecho = trecho[: trecho.find("\ndef ")]
    assert "astimezone()" in trecho, "iso_timestamp voltou a emitir carimbo sem fuso"
    assert "value.tzinfo is None" in trecho, (
        "iso_timestamp precisa distinguir ingênuo de ciente; converter um carimbo "
        "que já tem fuso seria perda de informação"
    )


def test_future_tolerance_is_declared():
    assert "COMMAND_SAMPLE_FUTURE_TOLERANCE_SECONDS" in ENGINE_SOURCE


# ------------------------------------------------------------------ comportamento


def local_naive(offset_seconds: float) -> str:
    """Carimbo ingênuo em hora local, `offset_seconds` no passado."""
    return (datetime.now().astimezone().replace(tzinfo=None)
            - timedelta(seconds=offset_seconds)).isoformat()


def test_the_production_case_now_confirms():
    """O caso exato do log: amostra ~60s antes do comando, carimbo sem fuso.

    Antes: aparecia 10739s atrás e era descartada. Agora precisa ser avaliada.
    """
    engine = load_engine_class()
    now = datetime.now().astimezone().timestamp()
    telemetry = {"captured_at": local_naive(60.0)}
    lag = engine._command_sample_lag(telemetry, now)
    assert lag is not None
    assert abs(lag - 60.0) < 5.0, f"atraso deveria ser ~60s, veio {lag}"
    assert not engine._command_sample_is_fresh(telemetry, now), (
        "amostra 60s ANTES do comando continua velha — o que muda é o tamanho do "
        "atraso relatado, não a regra"
    )


def test_sample_taken_after_the_command_is_fresh():
    engine = load_engine_class()
    now = datetime.now().astimezone().timestamp()
    telemetry = {"captured_at": local_naive(-5.0)}  # 5s depois do comando
    assert engine._command_sample_is_fresh(telemetry, now)
    lag = engine._command_sample_lag(telemetry, now)
    assert lag is not None and lag < 0


def test_naive_local_no_longer_looks_hours_old():
    """A regressão em uma linha: presumir UTC reintroduz o offset do host."""
    engine = load_engine_class()
    now = datetime.now().astimezone().timestamp()
    telemetry = {"captured_at": local_naive(1.0)}
    lag = engine._command_sample_lag(telemetry, now)
    assert lag is not None
    assert abs(lag) < 120.0, (
        f"atraso de {lag}s para amostra de 1s atrás: o carimbo voltou a ser lido "
        "no fuso errado"
    )
    # E especificamente: não pode estar perto do offset observado em produção.
    assert abs(abs(lag) - OBSERVED_OFFSET_SECONDS) > 600.0


def test_aware_timestamp_still_works():
    """Carimbo com fuso explícito não pode ser reinterpretado."""
    engine = load_engine_class()
    now = datetime.now(timezone.utc).timestamp()
    telemetry = {"captured_at": datetime.now(timezone.utc).isoformat()}
    lag = engine._command_sample_lag(telemetry, now)
    assert lag is not None and abs(lag) < 5.0
    telemetry_z = {"captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    lag_z = engine._command_sample_lag(telemetry_z, now)
    assert lag_z is not None and abs(lag_z) < 5.0


def test_absurd_future_sample_does_not_confirm():
    """Guarda contra errar a direção do fuso."""
    engine = load_engine_class()
    now = datetime.now().astimezone().timestamp()
    telemetry = {"captured_at": local_naive(-OBSERVED_OFFSET_SECONDS)}  # 3h no futuro
    assert not engine._command_sample_is_fresh(telemetry, now), (
        "amostra 3h no futuro foi aceita; se o fuso for interpretado na direção "
        "errada isso viraria confirmação falsa"
    )


def test_small_clock_skew_is_tolerated():
    """A nuvem chega ~1 min adiantada; isso é normal e não pode invalidar."""
    engine = load_engine_class()
    now = datetime.now().astimezone().timestamp()
    telemetry = {"captured_at": local_naive(-90.0)}
    assert engine._command_sample_is_fresh(telemetry, now)


@pytest.mark.parametrize("captured_at", [None, "", "nao-e-data", 12345])
def test_unusable_timestamp_presumes_fresh(captured_at):
    """Sem carimbo comparável, avaliar é melhor que descartar toda confirmação."""
    engine = load_engine_class()
    now = datetime.now().astimezone().timestamp()
    telemetry = {} if captured_at is None else {"captured_at": captured_at}
    assert engine._command_sample_is_fresh(telemetry, now)
    assert engine._command_sample_lag(telemetry, now) is None


def test_without_command_time_there_is_nothing_to_compare():
    engine = load_engine_class()
    telemetry = {"captured_at": local_naive(60.0)}
    assert engine._command_sample_is_fresh(telemetry, 0.0)
    assert engine._command_sample_lag(telemetry, 0.0) is None
