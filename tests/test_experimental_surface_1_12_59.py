"""Contrato 1.12.59 — o resto da superfície da biblioteca, sob liberação por proprietário.

Nove comandos entram no gate experimental, o mesmo do Sentinela: ficam fechados até
um administrador liberar o recurso para um proprietário específico, e ainda exigem a
confirmação explícita de quem aciona.

O que este contrato existe para proteger:

1. **Nenhum deles é estável.** Se um destes vazar para `COMMAND_METHODS`, passa a ser
   anunciado a todo mundo e o gate deixa de existir. Isto vale em especial para os dois
   que movem o carro.

2. **Os que movem o carro têm trava própria.** `autopark` e `piloted_parking` exigem
   `motion_acknowledged` além da confirmação experimental. Nenhum aplicativo consegue
   verificar que o dono está junto do carro; o que dá para garantir é que um toque
   distraído não baste.

3. **Pacote sem vocabulário documentado não vira túnel.** `seat_adjust` e
   `piloted_parking` são declarados na biblioteca só como "the full JSON payload
   string". O gateway confere a forma — objeto raso, chaves plausíveis, valores
   escalares, tetos de quantidade e tamanho — e recusa o resto.

4. **FOTA não sai com dado inventado.** `task_id` vem da listagem da nuvem e é
   obrigatório; o agendamento exige data e hora existentes.

Nenhuma asserção fixa a versão exata.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


connector = load_module("leaphub_surface_connector", ROOT / "leaphub_gateway" / "connector.py")

NEW_COMMANDS = {
    "autopark": 150,
    "piloted_parking": 350,
    "on3_on": 410,
    "on3_off": 410,
    "seat_adjust": 280,
    "rear_seats": 470,
    "fota_download": 390,
    "fota_install": 391,
    "fota_schedule": 392,
}


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in str(value).split("."))


class SurfaceClient:
    """Assinaturas iguais às da leapmotor_api 0.3.2."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def autopark(self, vin: str):
        self.calls.append(("autopark", {"vin": vin}))
        return {"accepted": True}

    def on3_on(self, vin: str):
        self.calls.append(("on3_on", {"vin": vin}))
        return {"accepted": True}

    def on3_off(self, vin: str):
        self.calls.append(("on3_off", {"vin": vin}))
        return {"accepted": True}

    def piloted_parking(self, vin: str, *, params: dict):
        self.calls.append(("piloted_parking", {"vin": vin, "params": params}))
        return {"accepted": True}

    def seat_adjust(self, vin: str, *, params: dict):
        self.calls.append(("seat_adjust", {"vin": vin, "params": params}))
        return {"accepted": True}

    def rear_seats(self, vin: str, *, seat_info: str):
        self.calls.append(("rear_seats", {"vin": vin, "seat_info": seat_info}))
        return {"accepted": True}

    def fota_download(self, vin: str, *, task_id: int):
        self.calls.append(("fota_download", {"vin": vin, "task_id": task_id}))
        return {"accepted": True}

    def fota_install(self, vin: str, *, task_id: int):
        self.calls.append(("fota_install", {"vin": vin, "task_id": task_id}))
        return {"accepted": True}

    def fota_schedule(self, vin: str, *, task_id: int, schedule_time: str):
        self.calls.append(("fota_schedule", {"vin": vin, "task_id": task_id, "schedule_time": schedule_time}))
        return {"accepted": True}


def test_version_never_regresses():
    assert version_tuple(connector.CONNECTOR_VERSION) >= version_tuple("1.12.59")


# ------------------------------------------------------------------ gate experimental


@pytest.mark.parametrize("command", sorted(NEW_COMMANDS))
def test_none_of_them_is_stable(command):
    """Vazar para a matriz estável anularia a liberação por proprietário."""
    assert command in connector.EXPERIMENTAL_COMMAND_METHODS, command
    assert command not in connector.COMMAND_METHODS, command


@pytest.mark.parametrize("command,right", sorted(NEW_COMMANDS.items()))
def test_each_one_declares_its_right(command, right):
    assert connector.COMMAND_REQUIRED_RIGHT[command] == right


def test_on3_does_have_a_right_code():
    """VehicleRight.ON3 = 410 existe, apesar de o comando não ter descrição funcional."""
    assert connector.COMMAND_REQUIRED_RIGHT["on3_on"] == 410
    assert connector.COMMAND_REQUIRED_RIGHT["on3_off"] == 410


def test_sentry_diagnostics_stay_with_sentry():
    assert connector.SENTRY_COMMANDS == {"sentry_on", "sentry_off"}
    for command in NEW_COMMANDS:
        assert command not in connector.SENTRY_COMMANDS, command


@pytest.mark.parametrize("command", sorted(NEW_COMMANDS))
def test_experimental_confirmation_is_required(command):
    """Sem confirmação explícita nada de rede acontece — nem sessão é aberta."""
    with pytest.raises(ValueError) as excinfo:
        connector.handle_command({
            "credentials": {"operation_password": "000000"},
            "vehicle_id": "TESTVIN0000000001",
            "command": command,
            "parameters": {},
        })
    assert "confirmação explícita" in str(excinfo.value)


# ------------------------------------------------------------------ movimento do carro


def test_only_the_two_motion_commands_need_the_extra_interlock():
    assert connector.VEHICLE_MOTION_COMMANDS == {"autopark", "piloted_parking"}


@pytest.mark.parametrize("command", ["autopark", "piloted_parking"])
def test_motion_commands_refuse_without_acknowledgement(command):
    """Confirmação experimental sozinha não basta para pôr o carro em movimento."""
    with pytest.raises(ValueError) as excinfo:
        connector.handle_command({
            "credentials": {"operation_password": "000000"},
            "vehicle_id": "TESTVIN0000000001",
            "command": command,
            "parameters": {"experimental_confirmed": "1"},
        })
    message = str(excinfo.value)
    assert "movimenta o veículo" in message
    assert "à vista" in message


@pytest.mark.parametrize("command", sorted(set(NEW_COMMANDS) - {"autopark", "piloted_parking"}))
def test_other_commands_do_not_demand_the_motion_acknowledgement(command):
    """O interlock é dos que movem o carro; nos outros seria atrito sem motivo.

    Sem `handle_command` de propósito: com a confirmação experimental presente
    estes comandos seguem adiante e chegam a abrir sessão, o que num ambiente com
    a biblioteca instalada sairia para a rede durante o teste. A garantia que
    importa é o interlock ser chaveado pelo conjunto, e isso se afirma direto.
    """
    assert command not in connector.VEHICLE_MOTION_COMMANDS


def test_autopark_is_dispatched_without_parameters():
    client = SurfaceClient()
    connector.execute_vehicle_command(client.autopark, "autopark", "VIN", {})
    assert client.calls == [("autopark", {"vin": "VIN"})]


@pytest.mark.parametrize("command", ["on3_on", "on3_off"])
def test_on3_is_dispatched_without_parameters(command):
    client = SurfaceClient()
    connector.execute_vehicle_command(getattr(client, command), command, "VIN", {})
    assert client.calls == [(command, {"vin": "VIN"})]


# ------------------------------------------------------------------ payload cru


def test_raw_payload_commands_are_exactly_the_undocumented_ones():
    assert connector.RAW_PAYLOAD_COMMANDS == {"seat_adjust", "piloted_parking"}


def test_raw_payload_accepts_a_flat_object():
    client = SurfaceClient()
    connector.execute_vehicle_command(
        client.seat_adjust, "seat_adjust", "VIN", {"payload": {"seat": 1, "angle": 30, "enable": True}}
    )
    assert client.calls[0][1]["params"] == {"seat": 1, "angle": 30, "enable": True}


def test_raw_payload_accepts_json_text():
    """O site pode mandar texto; o gateway interpreta e valida igual."""
    assert connector.raw_command_payload("seat_adjust", {"payload": '{"seat":2}'}) == {"seat": 2}


def test_raw_payload_accepts_one_level_of_nesting():
    result = connector.raw_command_payload("seat_adjust", {"payload": {"driver": {"angle": 20}}})
    assert result == {"driver": {"angle": 20}}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        "",
        "nao é json",
        "[1,2,3]",
        [1, 2, 3],
        {"campo": [1, 2]},
        {"campo": {"a": {"b": 1}}},
        {"bad key!": 1},
        {"1comeca_com_numero": 1},
        {"campo": None},
        {"campo": "x" * 121},
        {"campo": 10_000_001},
        {f"c{i}": i for i in range(13)},
        {"grande": "y" * 100, "grande2": "y" * 100, "grande3": "y" * 100, "grande4": "y" * 100,
         "grande5": "y" * 100, "grande6": "y" * 100},
    ],
)
def test_raw_payload_rejects_malformed_content(payload):
    client = SurfaceClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.seat_adjust, "seat_adjust", "VIN", {"payload": payload})
    assert client.calls == []


def test_raw_payload_rejects_too_many_nested_keys():
    with pytest.raises(ValueError):
        connector.raw_command_payload("seat_adjust", {"payload": {"a": {f"k{i}": i for i in range(9)}}})


def test_missing_raw_payload_is_refused():
    with pytest.raises(ValueError):
        connector.raw_command_payload("seat_adjust", {})


# ------------------------------------------------------------------ bancos traseiros


def test_rear_seats_forwards_the_seat_info():
    client = SurfaceClient()
    connector.execute_vehicle_command(client.rear_seats, "rear_seats", "VIN", {"seat_info": "1:2,3:0"})
    assert client.calls == [("rear_seats", {"vin": "VIN", "seat_info": "1:2,3:0"})]


@pytest.mark.parametrize("seat_info", ["", "   ", "x" * 121, "1:2 3:4", "drop table", "<script>"])
def test_rear_seats_rejects_unexpected_text(seat_info):
    client = SurfaceClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.rear_seats, "rear_seats", "VIN", {"seat_info": seat_info})
    assert client.calls == []


# ------------------------------------------------------------------ FOTA


@pytest.mark.parametrize("command", ["fota_download", "fota_install"])
def test_fota_requires_a_task_id(command):
    client = SurfaceClient()
    connector.execute_vehicle_command(getattr(client, command), command, "VIN", {"task_id": 42})
    assert client.calls == [(command, {"vin": "VIN", "task_id": 42})]


@pytest.mark.parametrize("parameters", [{}, {"task_id": 0}, {"task_id": -1}, {"task_id": "abc"}])
def test_fota_refuses_without_a_valid_task_id(parameters):
    client = SurfaceClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.fota_install, "fota_install", "VIN", parameters)
    assert client.calls == []


def test_fota_schedule_accepts_a_full_timestamp():
    client = SurfaceClient()
    connector.execute_vehicle_command(
        client.fota_schedule, "fota_schedule", "VIN", {"task_id": 7, "schedule_time": "2026-08-01 03:30:00"}
    )
    assert client.calls[0][1]["schedule_time"] == "2026-08-01 03:30:00"


@pytest.mark.parametrize(
    "schedule_time",
    ["", "2026-08-01", "01/08/2026 03:30:00", "2026-08-01T03:30:00", "2026-13-01 03:30:00", "2026-02-30 03:30:00"],
)
def test_fota_schedule_rejects_bad_timestamps(schedule_time):
    client = SurfaceClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(
            client.fota_schedule, "fota_schedule", "VIN", {"task_id": 7, "schedule_time": schedule_time}
        )
    assert client.calls == []
