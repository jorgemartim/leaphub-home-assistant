"""1.12.66 — a ordem de empilhamento vem do pacote oficial, não da biblioteca.

Relato do proprietário em 01/08/2026, com dois recortes: *"são duas coisas, a
porta e o porta-malas está sobrepondo o carro"*.

Compondo as camadas reais do C10 nas duas ordens, lado a lado, a diferença
aparece: na ordem da `leapmotor_api` o vidro e o caixilho da porta FECHADA são
carimbados sobre a porta ABERTA, e a tampa do porta-malas é desenhada na frente
do corpo. O proprietário confirmou qual das duas está certa.

A ordem canônica está nos prefixos numéricos dos arquivos do pacote:

    01 tailgate_open   02 body                03 leftbehind_window_close
    04 leftfront_window_close                 05 tailgate_close
    06 hood_open       07 leftbehind_open     08 leftfront_open
    09 rightbehind_open                       10 rightfront_open

`leapmotor_api._build_layer_list()` inverte dois pares: põe `tailgate_open`
depois de `body`, e os `*_window_close` depois das portas.

Estes testes afirmam a GARANTIA (quem vem antes de quem), nunca a lista
literal — acrescentar uma camada nova não pode reprovar a suíte, mas inverter
qualquer um dos dois pares tem de reprovar.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"não carregou {path.name}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONNECTOR = load_module("leaphub_layer_order_connector", APP / "connector.py")
pilha = CONNECTOR.official_layer_stack


def posicao(stack: list[str], nome: str) -> int:
    assert nome in stack, f"{nome} deveria estar na pilha: {stack}"
    return stack.index(nome)


# ----------------------------------------------------------- os dois defeitos


def test_tampa_aberta_fica_atras_do_corpo() -> None:
    """O recorte do proprietário: a tampa sobrepunha o carro."""
    stack = pilha(trunk_open=True)
    assert posicao(stack, "carpic_tailgate_open.png") < posicao(stack, "carpic_body.png")


def test_vidro_fechado_fica_atras_da_porta_aberta() -> None:
    """O outro recorte: o caixilho da porta fechada aparecia sobre a aberta."""
    stack = pilha(left_front_door_open=True, left_front_window_closed=True)
    assert posicao(stack, "carpic_leftfront_window_close.png") < posicao(
        stack, "carpic_leftfront_open.png"
    )


def test_o_mesmo_vale_para_a_porta_traseira() -> None:
    stack = pilha(left_rear_door_open=True, left_rear_window_closed=True)
    assert posicao(stack, "carpic_leftbehind_window_close.png") < posicao(
        stack, "carpic_leftbehind_open.png"
    )


# --------------------------------------------------------- controles negativos


def test_tampa_fechada_nao_desenha_camada_de_tampa() -> None:
    """1.12.68: o corpo já traz a tampa fechada; redesenhá-la a sobrepõe.

    Na 1.12.67 eu acrescentava `carpic_tailgate_close.png`, deduzida do prefixo
    05 do pacote da página de admin. No pacote que o gateway usa isso desenhava
    a tampa duas vezes, e o dono viu a sobreposição com o porta-malas FECHADO.
    """
    stack = pilha(trunk_open=False)
    assert "carpic_tailgate_open.png" not in stack
    assert "carpic_tailgate_close.png" not in stack


def test_nenhuma_camada_extra_alem_do_capo() -> None:
    """O simétrico do contrato de ausência: também não se pode ACRESCENTAR.

    Foi o que quebrou duas vezes seguidas — camadas deduzidas do pacote errado.
    A única adição legítima é `carpic_hood_open`, que a biblioteca nunca pede.
    """
    permitido = {"carpic_hood_open.png"}
    for estado in ESTADOS:
        extras = set(pilha(**estado)) - set(_biblioteca(**estado)) - permitido
        assert not extras, f"estado {estado} acrescentaria {sorted(extras)}"


def test_vidro_aberto_nao_desenha_o_vidro_fechado() -> None:
    stack = pilha(left_front_window_closed=False)
    assert "carpic_leftfront_window_close.png" not in stack


def test_porta_fechada_nao_desenha_camada_de_porta_aberta() -> None:
    """Nenhuma camada de porta ABERTA com o carro todo fechado.

    A camada de porta FECHADA, ao contrário, é obrigatória — ver
    `test_carro_todo_fechado_desenha_as_quatro_portas`. O pacote da página de
    admin não a tem; o que o gateway baixa da nuvem, tem.
    """
    stack = pilha()
    for nome in stack:
        assert "front_open" not in nome and "behind_open" not in nome, nome


def test_o_corpo_esta_sempre_presente() -> None:
    assert "carpic_body.png" in pilha()


# ------------------------------------------------------------------ capô (06)


def test_capo_aberto_entra_depois_do_corpo_e_antes_das_portas() -> None:
    """A camada existe no pacote; a biblioteca nunca a pede."""
    stack = pilha(hood_open=True, left_front_door_open=True)
    assert posicao(stack, "carpic_body.png") < posicao(stack, "carpic_hood_open.png")
    assert posicao(stack, "carpic_hood_open.png") < posicao(stack, "carpic_leftfront_open.png")


def test_capo_fechado_nao_desenha_nada() -> None:
    """Hoje a telemetria não traz capô: o padrão tem de ser não desenhar."""
    assert "carpic_hood_open.png" not in pilha()


# ---------------------------------------------------------------- carregamento


def test_camadas_de_carga_vem_por_ultimo() -> None:
    """No pacote as camadas de carga são 13+: sempre depois das portas."""
    stack = pilha(charging=True, left_front_door_open=True, trunk_open=True)
    ultima_porta = posicao(stack, "carpic_leftfront_open.png")
    assert posicao(stack, "carpic_charge_open.png") > ultima_porta


def test_quadro_de_carga_fora_da_faixa_cai_no_padrao() -> None:
    assert "carpic_charge2.png" in pilha(charging=True, charge_frame=99)
    assert "carpic_charge7.png" in pilha(charging=True, charge_frame=7)


def test_plugado_sem_carregar_usa_o_primeiro_quadro() -> None:
    stack = pilha(plugged=True)
    assert "carpic_charge1.png" in stack and "carpic_charge2.png" not in stack


# ------------------------------------------- a biblioteca continua sendo o erro


def test_a_ordem_da_biblioteca_seria_reprovada_por_este_contrato() -> None:
    """Controle negativo do contrato: a ordem antiga TEM de falhar aqui.

    Sem isto, um contrato que só lê a nossa lista passaria mesmo que alguém
    voltasse a delegar a ordem para `package.compose()`.
    """
    ordem_da_biblioteca = [
        "carpic_body.png",
        "carpic_leftfront_open.png",
        "carpic_tailgate_open.png",
        "carpic_leftfront_window_close.png",
    ]
    tampa_atras = ordem_da_biblioteca.index("carpic_tailgate_open.png") < ordem_da_biblioteca.index(
        "carpic_body.png"
    )
    vidro_atras = ordem_da_biblioteca.index(
        "carpic_leftfront_window_close.png"
    ) < ordem_da_biblioteca.index("carpic_leftfront_open.png")
    assert not tampa_atras, "a ordem da biblioteca punha a tampa na frente do corpo"
    assert not vidro_atras, "a ordem da biblioteca punha o vidro sobre a porta aberta"


# ------------------------------------------------------------------ 1.12.68
# A 1.12.66 foi ao ar sem estes: ela removia as camadas `*_close` de porta, que
# EXISTEM no pacote que o gateway baixa da nuvem, e o carro saiu sem as
# laterais. O modelo de pacote foi lido no da página de admin, que é outro.
# Nenhuma camada pode SUMIR em relação ao que a biblioteca desenharia.


def _biblioteca(**estado) -> list[str]:
    """A lista que `leapmotor_api._build_layer_list()` produziria."""
    from leapmotor_api.image import _build_layer_list
    from types import SimpleNamespace

    status = SimpleNamespace(
        doors=SimpleNamespace(
            rbcm_right_rear_door_status=estado.get("right_rear_door_open", False),
            rbcm_driver_door_status=estado.get("right_front_door_open", False),
            lbcm_left_rear_door_status=estado.get("left_rear_door_open", False),
            lbcm_driver_door_status=estado.get("left_front_door_open", False),
            bbcm_back_door_status=estado.get("trunk_open", False),
        ),
        windows=SimpleNamespace(
            left_front_window_percent=0 if estado.get("left_front_window_closed", True) else 50,
            left_rear_window_percent=0 if estado.get("left_rear_window_closed", True) else 50,
        ),
        is_plugged=False,
        is_charging=False,
    )
    return _build_layer_list(status)


ESTADOS = [
    {},
    {"trunk_open": True},
    {"left_front_door_open": True},
    {"left_rear_door_open": True},
    {"right_front_door_open": True},
    {"right_rear_door_open": True},
    {"trunk_open": True, "left_front_door_open": True},
    {"left_front_door_open": True, "left_front_window_closed": False},
]


def test_nenhuma_camada_da_biblioteca_pode_sumir() -> None:
    """O defeito da 1.12.68: o carro saiu sem as laterais."""
    for estado in ESTADOS:
        nossa = set(pilha(**estado))
        deles = set(_biblioteca(**estado))
        faltando = deles - nossa
        assert not faltando, f"estado {estado} perderia {sorted(faltando)}"


def test_carro_todo_fechado_desenha_as_quatro_portas() -> None:
    """Controle direto e legível do mesmo defeito."""
    stack = pilha()
    for nome in (
        "carpic_leftfront_close.png",
        "carpic_leftbehind_close.png",
        "carpic_rightfront_close.png",
        "carpic_rightbehind_close.png",
    ):
        assert nome in stack, f"{nome} sumiu: o carro sai sem lateral"


def test_a_porta_nunca_aparece_aberta_e_fechada_ao_mesmo_tempo() -> None:
    for estado in ESTADOS:
        stack = pilha(**estado)
        for lado in ("leftfront", "leftbehind", "rightfront", "rightbehind"):
            juntas = f"carpic_{lado}_open.png" in stack and f"carpic_{lado}_close.png" in stack
            assert not juntas, f"{lado} apareceu aberta e fechada em {estado}"
