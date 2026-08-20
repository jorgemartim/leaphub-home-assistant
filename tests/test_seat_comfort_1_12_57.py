"""Contrato 1.12.57 — comandos com parâmetro: conforto de assento e destino.

Duas garantias entram aqui.

A primeira é a matriz ganhar os dois primeiros comandos estáveis que não são de
argumento zero: `seat_heat` (301) e `seat_ventilation` (370). Desde a 1.12.121
o gateway não usa mais o wrapper numérico da biblioteca: ele envia o envelope
efetivo `position=driver|copilot` e `level=0..3` pelo primitivo remoto.

A segunda é uma regressão de campo: `send_destination` falhava sempre com
"Parâmetro de destino ainda não suportado pela biblioteca: address_name",
porque a leapmotor_api 0.3.2 exige o kwarg obrigatório `address_name` e o mapa
de valores do conector não o tinha. A introspecção de assinatura então tratava
um parâmetro obrigatório como não suportado e abortava antes de sair do gateway.

Nenhuma asserção fixa a versão exata: um contrato existe para provar que a
garantia introduzida aqui não regrediu, não para carimbar em que release o
repositório está.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_seat_comfort_connector", APP / "connector.py")


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in str(value).split("."))


class SeatClient:
    """Reproduz os wrappers legados e o primitivo da leapmotor_api 0.3.2."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.legacy_calls = 0

    def seat_heat(self, vin: str, *, position: int, level: int) -> dict[str, bool]:
        self.legacy_calls += 1
        return {"accepted": True}

    def seat_ventilation(self, vin: str, *, position: int, level: int) -> dict[str, bool]:
        self.legacy_calls += 1
        return {"accepted": True}

    def _remote_control(self, *, vin: str, action: str, cmd_content: str) -> dict[str, bool]:
        self.calls.append({"vin": vin, "action": action, "cmd_content": cmd_content})
        return {"accepted": True}


class DestinationClient:
    """Assinatura real de `send_destination` na 0.3.2, com `address_name`."""

    def __init__(self) -> None:
        self.received: dict[str, object] = {}

    def send_destination(
        self,
        vin: str,
        *,
        address: str,
        address_name: str,
        latitude: float,
        longitude: float,
    ) -> dict[str, bool]:
        self.received = {
            "vin": vin,
            "address": address,
            "address_name": address_name,
            "latitude": latitude,
            "longitude": longitude,
        }
        return {"accepted": True}


def test_version_never_regresses():
    """Não-regressão: `>=`, nunca igualdade — ver o cabeçalho deste arquivo."""
    assert version_tuple(connector.CONNECTOR_VERSION) >= version_tuple("1.12.57")


def test_seat_commands_are_in_the_stable_matrix():
    for command in ("seat_heat", "seat_ventilation"):
        assert command in connector.COMMAND_METHODS, command
        assert command not in connector.EXPERIMENTAL_COMMAND_METHODS, command
        assert connector.COMMAND_METHODS[command] == command


def test_seat_commands_declare_the_right_they_need():
    """301 = aquecimento de assento; 370 = ventilação. Sem isso o filtro de
    capacidade não consegue esconder o comando de quem não tem o hardware."""
    assert connector.COMMAND_REQUIRED_RIGHT["seat_heat"] == 301
    assert connector.COMMAND_REQUIRED_RIGHT["seat_ventilation"] == 370


def test_seat_commands_are_declared_as_parameterized():
    assert connector.SEAT_COMFORT_COMMANDS == {"seat_heat", "seat_ventilation"}


def test_capability_filter_hides_seat_heat_without_the_right():
    """Um carro que declara capacidade e não tem 301 não deve anunciar o comando."""
    assert connector.command_permitted_by_vehicle("seat_heat", {301})
    assert not connector.command_permitted_by_vehicle("seat_heat", {110, 170})
    # Fail-open preservado: sem dados de capacidade, nada é escondido.
    assert connector.command_permitted_by_vehicle("seat_heat", set())


def test_hardware_ability_implies_the_seat_rights():
    """A nuvem às vezes manda só `abilities`: 14 implica 301 e 42/43 implicam 370."""
    assert 301 in connector.effective_right_codes([], [14])
    assert 370 in connector.effective_right_codes([], [42])
    assert 370 in connector.effective_right_codes([], [43])


@pytest.mark.parametrize("command", ["seat_heat", "seat_ventilation"])
def test_seat_command_sends_verified_semantic_payload(command):
    client = SeatClient()
    result = connector.execute_vehicle_command(
        getattr(client, command), command, "TESTVIN0000000001", {"position": "copilot", "level": 3}
    )
    assert result == {"accepted": True}
    assert client.legacy_calls == 0
    assert client.calls == [{
        "vin": "TESTVIN0000000001",
        "action": command,
        "cmd_content": '{"position":"copilot","level":"3"}',
    }]


def test_seat_command_accepts_the_seat_prefixed_aliases():
    client = SeatClient()
    connector.execute_vehicle_command(
        client.seat_heat,
        "seat_heat",
        "TESTVIN0000000001",
        {"seat_position": "driver", "seat_level": 0},
    )
    assert client.calls == [{
        "vin": "TESTVIN0000000001",
        "action": "seat_heat",
        "cmd_content": '{"position":"driver","level":"0"}',
    }]


@pytest.mark.parametrize(
    "parameters",
    [
        {"position": 1, "level": 1},
        {"position": 2, "level": 1},
        {"position": 3, "level": 1},
        {"position": 6, "level": 1},
        {"position": "passenger", "level": 1},
        {"position": "rear_left", "level": 1},
    ],
)
def test_seat_command_rejects_legacy_or_unknown_position(parameters):
    client = SeatClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.seat_heat, "seat_heat", "VIN", parameters)
    assert client.calls == [], "nada pode chegar à nuvem com posição não comprovada"
    assert client.legacy_calls == 0


@pytest.mark.parametrize("level", [-1, 4, 9])
def test_seat_command_rejects_level_out_of_range(level):
    client = SeatClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(
            client.seat_heat, "seat_heat", "VIN", {"position": "driver", "level": level}
        )
    assert client.calls == []


@pytest.mark.parametrize(
    "parameters",
    [{}, {"position": "driver"}, {"level": 1}, {"position": "x", "level": 1}],
)
def test_seat_command_requires_both_values(parameters):
    client = SeatClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.seat_heat, "seat_heat", "VIN", parameters)
    assert client.calls == []


def test_send_destination_supplies_address_name():
    """A regressão de campo: sem `address_name` no mapa, isto levantava
    RuntimeError e o destino nunca saía do gateway."""
    client = DestinationClient()
    result = connector.execute_vehicle_command(
        client.send_destination,
        "send_destination",
        "TESTVIN0000000001",
        {"name": "Praia Grande", "address": "Rua A, 100", "latitude": -23.5, "longitude": -46.6},
    )
    assert result == {"accepted": True}
    assert client.received["address_name"] == "Praia Grande"
    assert client.received["address"] == "Rua A, 100"
    assert client.received["latitude"] == -23.5
    assert client.received["longitude"] == -46.6


def test_send_destination_still_rejects_impossible_coordinates():
    client = DestinationClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(
            client.send_destination,
            "send_destination",
            "VIN",
            {"name": "X", "address": "Y", "latitude": 91.0, "longitude": 0.0},
        )
    assert client.received == {}


def fake_vehicle(rights: list[int]) -> SimpleNamespace:
    """A biblioteca devolve um dataclass com `rights`/`abilities` como atributos, e
    o conector os lê com `getattr`. Um dict aqui daria falso verde: as chaves não
    seriam vistas, o filtro cairia no fail-open e o teste passaria por engano."""
    return SimpleNamespace(vin="TESTVIN0000000001", model="C10", rights=rights, abilities=[])


def test_seat_commands_are_announced_only_with_the_capability():
    """Ponta a ponta pela serialização: é ela que o site lê para montar a tela."""
    library = SeatClient()
    without_capability = connector.serialize_vehicle(fake_vehicle([110]), False, library)
    assert "seat_heat" not in without_capability["capabilities"]["supported_commands"]

    with_capability = connector.serialize_vehicle(fake_vehicle([110, 301, 370]), False, library)
    commands = with_capability["capabilities"]["supported_commands"]
    assert "seat_heat" in commands and "seat_ventilation" in commands
