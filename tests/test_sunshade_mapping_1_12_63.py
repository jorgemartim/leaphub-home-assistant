"""Contrato 1.12.63 — a cortina do teto lê o campo que a nuvem realmente publica.

No C10 e no B10 o vidro do teto é fixo; o único motor é o da cortina. A nuvem
publica o estado dela em `status.signal.1724`, que a `leapmotor_api` entrega como
`security.roof_opening` — e o connector consumia isso como teto solar.

Medido no carro do proprietário em 30/07/2026, nos dois sentidos:

| | cortina aberta | cortina fechada |
|---|---|---|
| `signal.1724` | 100 | 0 |
| `roof_open_percent` | 100 | 0 |
| `sunshade_open` | null | null |

O `signal.1256` subiu junto na abertura e **não voltou** ao fechar — reagia ao
carro acordar. Só o controle negativo separou os dois, e é por isso que este
contrato afirma o comportamento nos dois sentidos, nunca em um só.

O que este contrato protege:

1. Em C10/B10, sem campo de cortina próprio, `security.roof_opening` alimenta a
   cortina e o teto fica nulo — não pode voltar a espelhar a cortina no teto.
2. Um carro que publique o campo de cortina próprio continua com cada valor no
   seu lugar.
3. Modelo desconhecido não sofre a troca: o direito 160 aparece no `rightList`
   mesmo em carro de vidro fixo, então direito não prova mecanismo.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
SOURCE = (APP / "connector.py").read_text(encoding="utf-8")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_connector_sunshade_1_12_63", APP / "connector.py")


def resolve(roof_opening, sunshade_raw, model):
    """Reproduz a decisão do serialize_vehicle com as mesmas funções do módulo."""
    roof = connector.first_numeric(roof_opening)
    shade = connector.first_numeric(sunshade_raw)
    if (
        shade is None
        and roof is not None
        and connector.visual_model_family(model) in {"c10", "b10"}
    ):
        shade = roof
        roof = None
    return {
        "roof_percent": roof,
        "roof_open": connector.window_open(roof) if roof is not None else None,
        "sunshade_percent": shade,
        "sunshade_open": connector.window_open(shade) if shade is not None else None,
    }


def test_c10_cortina_aberta_vai_para_a_cortina():
    estado = resolve(100, None, "C10 BEV")
    assert estado["sunshade_open"] is True, "a cortina aberta continua sem chegar ao campo da cortina"
    assert estado["sunshade_percent"] == 100
    assert estado["roof_open"] is None, "o teto voltou a espelhar a cortina"
    assert estado["roof_percent"] is None


def test_c10_cortina_fechada_tambem():
    """O sentido que derrubou o candidato errado. Fechada é 0, não ausência."""
    estado = resolve(0, None, "C10 BEV")
    assert estado["sunshade_open"] is False
    assert estado["sunshade_percent"] == 0
    assert estado["roof_open"] is None


def test_b10_recebe_o_mesmo_tratamento():
    estado = resolve(100, None, "Leapmotor B10")
    assert estado["sunshade_open"] is True
    assert estado["roof_open"] is None


def test_carro_com_campo_proprio_de_cortina_nao_e_tocado():
    """Se a nuvem publica os dois, cada um fica no seu lugar."""
    estado = resolve(100, 0, "C10 BEV")
    assert estado["roof_percent"] == 100, "o teto perdeu o valor que era dele"
    assert estado["roof_open"] is True
    assert estado["sunshade_percent"] == 0
    assert estado["sunshade_open"] is False


def test_modelo_desconhecido_nao_sofre_a_troca():
    estado = resolve(100, None, "Leapmotor T99")
    assert estado["roof_percent"] == 100
    assert estado["roof_open"] is True
    assert estado["sunshade_open"] is None


def test_sem_dado_nenhum_continua_sem_dado():
    estado = resolve(None, None, "C10 BEV")
    assert estado["roof_open"] is None
    assert estado["sunshade_open"] is None


def test_a_troca_esta_condicionada_ao_modelo_no_codigo():
    """Guarda de forma: a condição não pode virar incondicional por descuido."""
    assert 'visual_model_family(model) in {"c10", "b10"}' in SOURCE
    assert "sunshade_position = roof_opening" in SOURCE
    assert "roof_opening = None" in SOURCE


def test_os_dois_comandos_continuam_com_direitos_distintos():
    """161 é a cortina e 160 é o teto solar; a correção não mistura os comandos."""
    assert connector.COMMAND_REQUIRED_RIGHT["sunshade_open"] == 161
    assert connector.COMMAND_REQUIRED_RIGHT["sunshade_close"] == 161
    assert connector.COMMAND_REQUIRED_RIGHT["sunroof_open"] == 160
    assert connector.COMMAND_REQUIRED_RIGHT["sunroof_close"] == 160
