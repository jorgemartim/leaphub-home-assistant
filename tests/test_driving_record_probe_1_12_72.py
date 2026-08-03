"""Contrato 1.12.72 — a leitura de diagnóstico do histórico da nuvem.

POR QUE ELA EXISTE. A telemetria ao vivo só enxerga o que o carro subiu, e o
carro para de subir enquanto roda. Medido em 31/07/2026, viagem de 94 km: das
112 leituras registradas, **72 eram a MESMA** — o Gateway perguntou 72 vezes ao
longo de 71 minutos e a nuvem devolveu sempre o mesmo instantâneo, enquanto 60 km
eram percorridos. O trecho de rodovia não existe na telemetria, e por isso a
média de velocidade do site não tem como bater com o computador de bordo.

A `leapmotor-api` expõe quatro leituras de HISTÓRICO que este conector nunca
chamou. Uma delas é `/carownerservice/oversea/drivingRecord/v1/mileage/energy/
detail` — o registro de condução do próprio carro, que **não depende da nossa
cadência**.

O QUE ESTE CONTRATO PROTEGE:

1. O diagnóstico chama os quatro métodos e sobrevive a método ausente e a
   método que levanta — é justamente saber QUAIS respondem que ele existe para
   descobrir.
2. Ele **não consome nada** e **não devolve valor bruto**: só a forma. Um
   diagnóstico que despeja o histórico do dono no log é vazamento.
3. A rota HTTP passa pelas MESMAS travas das outras leituras de conta: ela fala
   com a Leapmotor e não pode furar a fila nem competir com um comando.
4. Nada foi ligado no caminho automático: nenhuma cadência mudou, e a telemetria
   não passou a chamar o histórico sozinha.

Nenhuma asserção fixa a versão exata.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if "leaphub_connector" not in sys.modules:
    load_module("leaphub_connector", APP / "connector.py")
connector = sys.modules["leaphub_connector"]

CONNECTOR = (APP / "connector.py").read_text(encoding="utf-8")
SERVER = (APP / "connector_server.py").read_text(encoding="utf-8")
ENGINE = (APP / "telemetry_engine.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1
def test_probe_covers_the_four_history_reads() -> None:
    metodos = connector.DRIVING_RECORD_METHODS
    assert "get_mileage_energy_detail" in metodos, "o drivingRecord e o motivo desta leitura"
    assert len(metodos) >= 4, f"a sonda cobre so {len(metodos)} leitura(s)"
    # O endpoint que importa tem de estar na biblioteca com esse nome.
    assert "drivingRecord" in CONNECTOR, "o endereco do registro de conducao saiu do codigo"


def test_probe_survives_missing_and_failing_methods() -> None:
    """Saber QUAIS respondem e o objetivo; uma falha nao pode calar as outras."""

    class ClienteParcial:
        """Um metodo responde, um levanta, dois nao existem."""

        def login(self): ...
        def close(self): ...
        def get_vehicle_list(self):
            return [{"vin": "VIN123", "car_id": "car-1"}]

        def get_mileage_energy_detail(self, vehicle):
            return {"data": {"records": [{"mileage": 94.0, "energy": 17.55}]}}

        def get_consumption_last_week_breakdown(self, vehicle):
            raise RuntimeError("nao habilitado para esta conta")

    original = connector.create_client
    connector.create_client = lambda *a, **k: ClienteParcial()
    try:
        resultado = connector.handle_driving_record({"credentials": {}, "vehicle_id": "VIN123"})
    finally:
        connector.create_client = original

    assert resultado["ok"] is True
    por_nome = {item["metodo"]: item for item in resultado["leituras"]}
    assert len(por_nome) == len(connector.DRIVING_RECORD_METHODS)

    assert por_nome["get_mileage_energy_detail"]["ok"] is True
    assert por_nome["get_consumption_last_week_breakdown"]["existe"] is True
    assert por_nome["get_consumption_last_week_breakdown"]["ok"] is False, (
        "um metodo que levanta tem de aparecer como falha, nao sumir"
    )
    assert por_nome["get_consumption_weekly_rank"]["existe"] is False
    assert por_nome["get_charging_daily_detail"]["existe"] is False


# ---------------------------------------------------------------- 2
def test_probe_reports_shape_never_values() -> None:
    """Diagnostico que despeja o historico do dono e vazamento.

    O payload e RASO de proposito. Numa versao anterior deste contrato ele era
    aninhado, e os valores sumiam do resultado pelo CORTE DE PROFUNDIDADE, nao
    pelo trabalho de `describe_shape`: o teste passava mesmo com o ramo de texto
    e o de numero devolvendo o valor cru. Foi o controle negativo que acusou —
    duas mutacoes que vazavam valor nao eram detectadas.
    """
    raso = {
        "mileage": 94.7,
        "energy": 17.55,
        "trips": 3,
        "startTime": "2026-07-31 09:37:36",
        "vin": "LFZB5AE23TD174014",
        "shared": True,
        "endTime": None,
    }
    forma = connector.describe_shape(raso)
    texto = repr(forma)

    # Nenhum valor sobrevive.
    for vazado in ("94.7", "17.55", "2026-07-31", "LFZB5AE23TD174014"):
        assert vazado not in texto, f"o diagnostico vazou um valor: {vazado}"
    # Mas os NOMES dos campos sobrevivem — e para isso que ele existe.
    for campo in ("mileage", "energy", "startTime", "vin"):
        assert campo in texto, f"o diagnostico perdeu o nome do campo {campo}"
    # E cada tipo vira uma descricao, nao o valor.
    assert forma["mileage"].startswith("float"), forma["mileage"]
    assert forma["energy"].startswith("float"), forma["energy"]
    assert forma["trips"].startswith("int"), forma["trips"]
    assert forma["startTime"].startswith("texto["), forma["startTime"]
    assert forma["vin"].startswith("texto["), forma["vin"]
    assert forma["shared"] == "bool"
    assert forma["endTime"] == "nulo"

    # Estrutura de lista: quantos itens, e a forma do primeiro.
    lista = connector.describe_shape({"records": [{"mileage": 94.7}, {"mileage": 12.0}]})
    assert lista["records"]["lista"] == 2
    assert lista["records"]["primeiro_item"]["mileage"].startswith("float")
    assert "94.7" not in repr(lista)

    # CONTROLE: profundidade nao pode explodir num payload aninhado.
    fundo = {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}
    assert "profundidade cortada" in repr(connector.describe_shape(fundo))


# ---------------------------------------------------------------- 3
def test_route_shares_the_account_lock_with_other_reads() -> None:
    assert '"/v1/vehicles/driving-record"' in SERVER, "a rota nao esta na allowlist de POST"
    inicio = SERVER.index("account_lock = account_operation_lock(")
    fim = SERVER.index('elif self.path == "/v1/vehicles/sync"', inicio)
    bloco = SERVER[inicio:fim]
    # Presenca da string nao basta: `if False and self.path == "..."` deixaria o
    # literal no lugar e o despacho morto. A asserção olha o DESPACHO.
    assert re.search(r'^\s*if self\.path == "/v1/vehicles/driving-record":\s*$', bloco, re.M), (
        "o diagnostico ficou fora da trava de conta e competiria com um comando do dono"
    )


# ---------------------------------------------------------------- 4
def test_nothing_was_wired_into_the_automatic_path() -> None:
    """A sonda e manual. Ligar no ciclo automatico e outra decisao, com custo."""
    for nome in ("get_mileage_energy_detail", "handle_driving_record"):
        assert nome not in ENGINE, (
            f"{nome} entrou no motor de telemetria: o historico passou a ser lido sozinho"
        )
    # E a cadencia continua a mesma.
    assert "self.command_cadence = (self.command_seconds, 20, 35, 45, 60, 90, 120, 120)" in ENGINE
