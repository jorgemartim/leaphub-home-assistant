"""1.12.65 — carro acordado é lido rápido; só o que dorme cai para lento.

Relato do proprietário em 01/08/2026: *"agora nesse instante o porta-malas está
aberto porém ali não mostra"*. Medido no site no mesmo minuto: `captured_at`
travado 12 minutos atrás, `trunk_open: false`.

A causa está em `_adaptive_interval`: parado devolve `parked_seconds` (90s) só
nas seis primeiras leituras e depois rebaixa para `sleep_seconds` (600s). Seis
vezes noventa são nove minutos — o critério de "dormindo" era o **relógio**,
nunca o carro. Um veículo na garagem há mais de nove minutos já estava na
cadência de sono quando o dono abriu o porta-malas.

Aqui a atividade observada passa a decidir. Mexer no carro — porta, porta-malas,
capô, vidro, cortina ou trava — prova que ele está acordado e recomeça a
contagem. O que não muda continua barato: parado de verdade ainda dorme.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"não carregou {path.name}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_engine_class():
    """Carrega a classe do motor.

    `telemetry_engine.py` faz `import leaphub_connector`, que no add-on
    instalado é o `connector.py` copiado para site-packages. Registrar o arquivo
    sob esse nome antes resolve o import — mesmo caminho de
    `test_command_sample_timezone_1_12_61.py`.
    """
    if "leaphub_connector" not in sys.modules:
        load_module("leaphub_connector", APP / "connector.py")
    module = load_module("leaphub_awake_engine", APP / "telemetry_engine.py")
    for value in vars(module).values():
        if hasattr(value, "activity_fingerprint") and hasattr(value, "_adaptive_interval"):
            return value
    raise AssertionError("classe do motor não encontrada em telemetry_engine.py")


ENGINE = load_engine_class()
impressao = ENGINE.activity_fingerprint
recomeca = ENGINE.parked_streak_after_activity


class _Cadencias:
    """Só os números que `_adaptive_interval` consulta, com os padrões reais."""

    active_seconds = 20
    interactive_seconds = 20
    charging_seconds = 25
    charge_watch_seconds = 60
    parked_seconds = 90
    sleep_seconds = 600
    command_cadence = (12, 20, 35, 45, 60, 90, 120, 120)


def _intervalo(streak: int) -> tuple[int, str, int]:
    return ENGINE._adaptive_interval(_Cadencias(), ["parked"], streak)


def _telemetria(**mudancas: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "doors": {"front_left": False, "front_right": False, "rear_left": False, "rear_right": False, "trunk": False},
        "locked": True,
        "windows": False,
        "sunshade_open": False,
        "hood_open": False,
        "plugged": False,
        "battery_soc": 62,
        "range_km": 310,
    }
    portas = mudancas.pop("doors", None)
    if portas:
        base["doors"] = {**base["doors"], **portas}
    base.update(mudancas)
    return base


def test_o_defeito_relatado_o_relogio_rebaixava_carro_acordado() -> None:
    """Na sexta leitura parada a cadência caía para 600s sem consultar o carro."""
    assert _intervalo(5)[0] == 90, "antes do limiar a leitura ainda é rápida"
    lento, estado, _ = _intervalo(6)
    assert lento == 600 and estado == "sleep", "o rebaixamento por relógio existe"


def test_atividade_devolve_a_cadencia_rapida() -> None:
    """A garantia: porta-malas aberto com a contagem estourada volta a 90s."""
    rapido, estado, _ = _intervalo(recomeca(9, activity_changed=True))
    assert rapido == 90, "carro em que alguém mexeu não pode esperar 600s"
    assert estado == "parked"


def test_sem_atividade_a_economia_e_preservada() -> None:
    """Controle negativo: sem mudança nada é zerado, e o carro parado dorme."""
    assert recomeca(9, activity_changed=False) == 9
    assert _intervalo(recomeca(9, activity_changed=False))[0] == 600


def test_aberturas_tranca_e_cortina_contam_como_atividade() -> None:
    parado = impressao(_telemetria())
    for descricao, telemetria in {
        "porta-malas": _telemetria(doors={"trunk": True}),
        "porta traseira direita": _telemetria(doors={"rear_right": True}),
        "capô": _telemetria(hood_open=True),
        "cortina": _telemetria(sunshade_open=True),
        "tranca": _telemetria(locked=False),
        "vidros": _telemetria(windows=True),
        "cabo": _telemetria(plugged=True),
    }.items():
        assert impressao(telemetria) != parado, f"{descricao} deveria contar como atividade"


def test_bateria_e_autonomia_nao_sao_atividade() -> None:
    """Controle negativo: o que oscila com o carro dormindo não pode acordá-lo.

    Sem isto a impressão digital mudaria a cada leitura e a cadência rápida
    valeria para sempre — o oposto do que o proprietário pediu.
    """
    assert impressao(_telemetria(battery_soc=61, range_km=305)) == impressao(_telemetria())


def test_o_registro_e_por_assinatura() -> None:
    """Um carro não pode zerar nem calar a contagem de outro."""
    registro = ENGINE._ACTIVITY_REGISTRY
    registro.clear()
    registro["assinatura-a"] = impressao(_telemetria())

    mudou_a = registro.get("assinatura-a") != impressao(_telemetria())
    mudou_b = registro.get("assinatura-b") != impressao(_telemetria())

    assert mudou_a is False, "mesmo estado no mesmo carro não é atividade"
    assert mudou_b is True, "carro sem registro ainda não tem comparação"
    registro.clear()


def test_a_primeira_leitura_nunca_conta_como_atividade() -> None:
    """Sem leitura anterior não há mudança: só um `None` vira atividade falsa."""
    registro = ENGINE._ACTIVITY_REGISTRY
    registro.clear()
    anterior = registro.get("assinatura-nova")
    assert anterior is None
    assert (anterior is not None and anterior != impressao(_telemetria())) is False
