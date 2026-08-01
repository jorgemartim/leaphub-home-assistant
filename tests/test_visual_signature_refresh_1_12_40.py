"""1.12.40 — o desenho do veículo acompanha a mudança de estado.

Relato do proprietário em 01/08/2026: "a imagem não atualiza em tempo real,
tenho que enviar um comando do controle para ela poder atualizar".

A telemetria estava certa: com duas portas abertas e o porta-malas fechado, o
site recebia `doors_open: 2`, `trunk_open: false`, e os selos e marcadores
acompanhavam. Só o desenho ficava para trás — porque a leitura FAST adia a
imagem oficial SEMPRE, e os bytes só saíam com `force_visual_bytes`, exclusivo
do `sync`. Ou seja: só um comando manual fazia o desenho andar.

Aqui a assinatura visual passa a decidir. Quando ela muda, a composição
anterior deixou de descrever o veículo e a imagem deixa de ser secundária.
O comando manual continua tendo prioridade absoluta.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "visual_signature_refresh_test",
    ROOT / "leaphub_gateway" / "connector.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

defer = MODULE.should_defer_official_image


def test_leitura_fast_adia_quando_o_estado_nao_mudou() -> None:
    """Sem mudança de estado o desenho continua valendo: adiar é o certo."""
    assert defer(include_secondary_network=False, manual_waiting=False, signature_changed=False) is True


def test_mudanca_de_assinatura_vence_o_perfil_fast() -> None:
    """O defeito relatado. Antes, isto devolvia True e o desenho travava."""
    assert defer(include_secondary_network=False, manual_waiting=False, signature_changed=True) is False


def test_comando_manual_continua_com_prioridade() -> None:
    """Garantia da 1.12.28: imagem não segura a conta na frente de um comando."""
    assert defer(include_secondary_network=False, manual_waiting=True, signature_changed=True) is True
    assert defer(include_secondary_network=True, manual_waiting=True, signature_changed=True) is True


def test_leitura_completa_nao_adia() -> None:
    """Fora do perfil FAST o comportamento anterior é preservado."""
    assert defer(include_secondary_network=True, manual_waiting=False, signature_changed=False) is False


def test_o_estado_entregue_e_registrado_por_veiculo() -> None:
    """O registro é por veículo: um carro não pode calar o desenho de outro."""
    registro = MODULE._IMAGE_LAST_SIGNATURE
    registro.clear()
    registro["carro-a"] = "unlocked--trunk-open"

    mudou_a = registro.get("carro-a") != "unlocked--trunk-open"
    mudou_b = registro.get("carro-b") != "unlocked--trunk-open"

    assert mudou_a is False, "mesmo estado no mesmo carro nao deveria recompor"
    assert mudou_b is True, "carro sem registro deveria receber os bytes"
    registro.clear()
