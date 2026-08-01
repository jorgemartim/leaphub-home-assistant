"""1.12.39 → reescrito na 1.12.66: a porta aberta não pode sair com vidro em cima.

A garantia é a mesma desde a 1.12.39; o mecanismo mudou.

Até a 1.12.65 ela era obtida **depois** da composição: compunha-se a cena duas
vezes (porta aberta e fechada), tirava-se a diferença e repintava-se um polígono
de frações fixas. Este contrato afirmava esse mecanismo — `restored_pixels > 500`
— e por isso reprovaria a própria correção que o tornou desnecessário.

A causa real era a ORDEM das camadas: `leapmotor_api._build_layer_list()`
acrescenta `carpic_leftfront_window_close` **depois** de `carpic_leftfront_open`,
carimbando o vidro da porta fechada sobre a porta aberta. Com a ordem do pacote
oficial (vidro em 04, porta em 08) não há artefato para apagar.

O contrato passa a afirmar a garantia: **o vidro fechado nunca fica acima da
porta aberta**, e o caminho de contingência não corrompe bytes. A ordem em si é
exercitada em `test_official_layer_order_1_12_66.py`.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "open_door_visual_test",
    ROOT / "leaphub_gateway" / "connector.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["open_door_visual_test"] = MODULE
SPEC.loader.exec_module(MODULE)


class _LayerPackage:
    """Dublê com a mesma interface do `CarImagePackage` real.

    O pacote oficial é `CarImagePackage.from_zip(...)` (connector.py:2098), que
    expõe `_composite_layers` e `_export` — é por eles que a composição passa.
    """

    def __init__(self) -> None:
        def cor(rgba):
            return Image.new("RGBA", (40, 20), rgba)

        self._images = {
            "carpic_body.png": cor((225, 225, 225, 255)),
            "carpic_tailgate_open.png": cor((10, 10, 10, 255)),
            "carpic_tailgate_close.png": cor((200, 200, 200, 255)),
            "carpic_leftfront_window_close.png": cor((55, 60, 66, 255)),
            "carpic_leftfront_open.png": cor((232, 140, 90, 255)),
        }
        self.compose_chamado = False

    def _composite_layers(self, layer_names):
        canvas = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
        for name in layer_names:
            layer = self._images.get(name)
            if layer is not None:
                canvas = Image.alpha_composite(canvas, layer)
        return canvas

    @staticmethod
    def _export(canvas, fmt="PNG"):
        buffer = io.BytesIO()
        canvas.save(buffer, format=fmt)
        return buffer.getvalue()

    def compose(self, status, **_options):
        self.compose_chamado = True
        return self._export(self._composite_layers(["carpic_body.png"]))


def _status(**doors):
    base = {
        "bbcm_back_door_status": False,
        "lbcm_driver_door_status": False,
        "lbcm_left_rear_door_status": False,
        "rbcm_driver_door_status": False,
        "rbcm_right_rear_door_status": False,
    }
    base.update(doors)
    return SimpleNamespace(
        doors=SimpleNamespace(**base),
        windows=SimpleNamespace(left_front_window_percent=0, left_rear_window_percent=0),
        battery=SimpleNamespace(is_charging=False),
        is_plugged=False,
    )


def test_a_porta_aberta_nunca_sai_com_o_vidro_fechado_por_cima() -> None:
    """O defeito relatado em 01/08/2026, com o recorte da tela."""
    package = _LayerPackage()
    raw, restaurados = MODULE._compose_official_frame(package, _status(lbcm_driver_door_status=True))

    topo = Image.open(io.BytesIO(raw)).convert("RGBA").getpixel((20, 10))
    assert topo == (232, 140, 90, 255), f"a porta deveria estar por cima; veio {topo}"
    assert restaurados == 0, "não há mais repintura: a ordem resolve"
    assert not package.compose_chamado, "a ordem não pode voltar a ser delegada à biblioteca"


def test_a_tampa_aberta_nunca_sai_por_cima_do_corpo() -> None:
    """O segundo recorte do proprietário."""
    package = _LayerPackage()
    raw, _ = MODULE._compose_official_frame(package, _status(bbcm_back_door_status=True))

    topo = Image.open(io.BytesIO(raw)).convert("RGBA").getpixel((20, 10))
    assert topo != (10, 10, 10, 255), "a tampa aberta ficou na frente do corpo"


def test_porta_fechada_preserva_os_bytes() -> None:
    """Garantia original da 1.12.39: sem porta aberta, nada é reprocessado."""
    package = _LayerPackage()
    # A lista esperada vem da própria função: fixá-la à mão faz o contrato
    # reprovar por cosmética a cada camada nova, sem defeito nenhum.
    esperado = package._export(package._composite_layers(MODULE.official_layer_stack()))
    obtido, restaurados = MODULE._compose_official_frame(package, _status())
    assert restaurados == 0
    assert obtido == esperado


def test_pacote_sem_camadas_cai_para_a_biblioteca_sem_quebrar() -> None:
    """Contingência: um pacote antigo, só com `compose()`, ainda funciona."""

    class _SoCompose:
        def compose(self, status, **_options):
            buffer = io.BytesIO()
            Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(buffer, format="PNG")
            return buffer.getvalue()

    raw, restaurados = MODULE._compose_official_frame(_SoCompose(), _status(lbcm_driver_door_status=True))
    assert restaurados == 0
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
