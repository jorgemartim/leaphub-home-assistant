"""Contrato 1.12.58 — paridade de comandos: teto solar, janela, limite, mídia e preparo.

Seis comandos entram na matriz estável e um no gate experimental. O que este
contrato existe para proteger:

1. **Teto solar não é a cortina do teto.** `sunroof_open/close` (comando 300)
   exigem o direito **160**; `sunshade_open/close` exigem **161**. Trocar os dois
   faria o comando aparecer para quem não tem o hardware e sumir para quem tem.

2. **Nada com valor livre chega à nuvem sem conferência.** Posição de janela,
   limite de velocidade, operação de mídia e o envelope do `prepare_car` são
   validados no gateway; fora de faixa é recusado antes de qualquer requisição.

3. **`prepare_car` monta um envelope allow-listed.** A biblioteca serializa o
   dicionário sem validar nada, então o conteúdo é construído aqui a partir de
   parâmetros nomeados — nunca repassado do site — e só com as dimensões pedidas.

4. **O Sentinela não empresta seu diagnóstico.** `SENTRY_COMMANDS` deixou de ser
   derivado de `EXPERIMENTAL_COMMAND_METHODS` para que `prepare_car` não seja
   tratado como sonda do Sentinela.

Nenhuma asserção fixa a versão exata: o contrato prova que a garantia não
regrediu, não em que release o repositório está.
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


connector = load_module("leaphub_parity_connector", APP / "connector.py")


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in str(value).split("."))


class ParityClient:
    """Assinaturas iguais às da leapmotor_api 0.3.2 para os comandos novos."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def open_sunroof(self, vin: str) -> dict[str, bool]:
        self.calls.append(("open_sunroof", {"vin": vin}))
        return {"accepted": True}

    def close_sunroof(self, vin: str) -> dict[str, bool]:
        self.calls.append(("close_sunroof", {"vin": vin}))
        return {"accepted": True}

    def windows(self, vin: str, *, value: str | None = None) -> dict[str, bool]:
        self.calls.append(("windows", {"vin": vin, "value": value}))
        return {"accepted": True}

    def set_speed_limit(self, vin: str, *, value: str) -> dict[str, bool]:
        self.calls.append(("set_speed_limit", {"vin": vin, "value": value}))
        return {"accepted": True}

    def music(self, vin: str, *, operation: str) -> dict[str, bool]:
        self.calls.append(("music", {"vin": vin, "operation": operation}))
        return {"accepted": True}

    def video(self, vin: str, *, operation: str) -> dict[str, bool]:
        self.calls.append(("video", {"vin": vin, "operation": operation}))
        return {"accepted": True}

    def prepare_car(self, vin: str, *, params: dict[str, object]) -> dict[str, bool]:
        self.calls.append(("prepare_car", {"vin": vin, "params": params}))
        return {"accepted": True}


def vehicle_with(rights: list[int]) -> SimpleNamespace:
    """`rights`/`abilities` são atributos no dataclass da biblioteca, e o conector
    os lê com getattr: um dict aqui cairia no fail-open e daria falso verde."""
    return SimpleNamespace(vin="TESTVIN0000000001", model="C10", rights=rights, abilities=[])


def test_version_never_regresses():
    assert version_tuple(connector.CONNECTOR_VERSION) >= version_tuple("1.12.58")


# --------------------------------------------------------------------------- matriz


def test_stable_matrix_has_the_six_new_commands():
    expected = {
        "sunroof_open": "open_sunroof",
        "sunroof_close": "close_sunroof",
        "windows_position": "windows",
        "set_speed_limit": "set_speed_limit",
        "music": "music",
        "video": "video",
    }
    for command, method in expected.items():
        assert connector.COMMAND_METHODS.get(command) == method, command
        assert command not in connector.EXPERIMENTAL_COMMAND_METHODS, command


def test_prepare_car_is_experimental_not_stable():
    """Enquanto o pacote do comando imediato não for confirmado em tráfego real,
    ele exige confirmação explícita do proprietário."""
    assert connector.EXPERIMENTAL_COMMAND_METHODS.get("prepare_car") == "prepare_car"
    assert "prepare_car" not in connector.COMMAND_METHODS


def test_sunroof_and_sunshade_are_different_rights():
    """160 = teto solar, 161 = cortina do teto. É o par mais fácil de trocar."""
    assert connector.COMMAND_REQUIRED_RIGHT["sunroof_open"] == 160
    assert connector.COMMAND_REQUIRED_RIGHT["sunroof_close"] == 160
    assert connector.COMMAND_REQUIRED_RIGHT["sunshade_open"] == 161
    assert connector.COMMAND_REQUIRED_RIGHT["sunshade_close"] == 161


def test_new_commands_declare_their_rights():
    assert connector.COMMAND_REQUIRED_RIGHT["windows_position"] == 230
    assert connector.COMMAND_REQUIRED_RIGHT["set_speed_limit"] == 510
    assert connector.COMMAND_REQUIRED_RIGHT["music"] == 270
    assert connector.COMMAND_REQUIRED_RIGHT["video"] == 290
    assert connector.COMMAND_REQUIRED_RIGHT["prepare_car"] == 360


def test_every_command_still_declares_a_right():
    """Anti-deriva: comando novo sem direito não pode ser filtrado por capacidade."""
    missing = [c for c in connector.ALL_COMMAND_METHODS if c not in connector.COMMAND_REQUIRED_RIGHT]
    assert missing == [], missing


def test_sentry_diagnostics_are_not_shared_with_other_experimentals():
    assert connector.SENTRY_COMMANDS == {"sentry_on", "sentry_off"}
    assert "prepare_car" not in connector.SENTRY_COMMANDS


# --------------------------------------------------------------------------- teto solar


@pytest.mark.parametrize("command,method", [("sunroof_open", "open_sunroof"), ("sunroof_close", "close_sunroof")])
def test_sunroof_is_dispatched_without_parameters(command, method):
    client = ParityClient()
    result = connector.execute_vehicle_command(getattr(client, method), command, "VIN", {})
    assert result == {"accepted": True}
    assert client.calls == [(method, {"vin": "VIN"})]


def test_sunroof_is_announced_only_with_right_160():
    client = ParityClient()
    without = connector.serialize_vehicle(vehicle_with([161]), False, client)
    assert "sunroof_open" not in without["capabilities"]["supported_commands"]
    assert "sunshade_open" not in without["capabilities"]["supported_commands"], (
        "a cortina precisa do método na biblioteca, que este dublê não tem"
    )
    with_right = connector.serialize_vehicle(vehicle_with([160]), False, client)
    assert "sunroof_open" in with_right["capabilities"]["supported_commands"]
    assert "sunroof_close" in with_right["capabilities"]["supported_commands"]


# --------------------------------------------------------------------------- janela


def test_window_position_is_sent_as_text():
    client = ParityClient()
    connector.execute_vehicle_command(client.windows, "windows_position", "VIN", {"window_position": 40})
    assert client.calls == [("windows", {"vin": "VIN", "value": "40"})]


@pytest.mark.parametrize("value", [0, 100])
def test_window_position_accepts_the_extremes(value):
    client = ParityClient()
    connector.execute_vehicle_command(client.windows, "windows_position", "VIN", {"value": value})
    assert client.calls[0][1]["value"] == str(value)


@pytest.mark.parametrize("parameters", [{"value": -1}, {"value": 101}, {}, {"value": "meio"}])
def test_window_position_rejects_invalid_values(parameters):
    client = ParityClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.windows, "windows_position", "VIN", parameters)
    assert client.calls == []


# --------------------------------------------------------------------------- limite


def test_speed_limit_is_sent_as_text():
    client = ParityClient()
    connector.execute_vehicle_command(client.set_speed_limit, "set_speed_limit", "VIN", {"speed_limit_kmh": 80})
    assert client.calls == [("set_speed_limit", {"vin": "VIN", "value": "80"})]


@pytest.mark.parametrize("parameters", [{"value": 29}, {"value": 201}, {}, {"value": "rapido"}])
def test_speed_limit_rejects_values_outside_the_range(parameters):
    client = ParityClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.set_speed_limit, "set_speed_limit", "VIN", parameters)
    assert client.calls == []


# --------------------------------------------------------------------------- mídia


def test_media_vocabulary_matches_the_library():
    assert connector.MEDIA_COMMANDS == {"music", "video"}
    assert connector.MEDIA_OPERATIONS == {"play", "pause", "next", "previous"}


@pytest.mark.parametrize("command", ["music", "video"])
@pytest.mark.parametrize("operation", ["play", "pause", "next", "previous"])
def test_media_operations_are_forwarded(command, operation):
    client = ParityClient()
    connector.execute_vehicle_command(getattr(client, command), command, "VIN", {"operation": operation})
    assert client.calls == [(command, {"vin": "VIN", "operation": operation})]


def test_media_operation_is_normalized():
    client = ParityClient()
    connector.execute_vehicle_command(client.music, "music", "VIN", {"operation": "  PLAY  "})
    assert client.calls[0][1]["operation"] == "play"


@pytest.mark.parametrize("parameters", [{}, {"operation": "stop"}, {"operation": ""}])
def test_media_rejects_unknown_operations(parameters):
    client = ParityClient()
    with pytest.raises(ValueError):
        connector.execute_vehicle_command(client.music, "music", "VIN", parameters)
    assert client.calls == []


# --------------------------------------------------------------------------- prepare_car


def test_prepare_car_builds_only_the_requested_dimensions():
    params = connector.prepare_car_parameters({"climate": True, "temperature": 22, "climate_mode": "hot"})
    assert set(params) == {"air_condition"}
    assert params["air_condition"]["temperature"] == "22"
    assert params["air_condition"]["mode"] == "hot"
    # 1.12.103: hot/cold/wind sao escolhas explicitas e usam operacao manual.
    assert params["air_condition"]["operate"] == "manual"
    assert params["air_condition"]["position"] == "all"
    assert params["air_condition"]["wshld"] == "0"


def test_prepare_car_accepts_the_three_known_dimensions():
    params = connector.prepare_car_parameters({
        "climate": True,
        "temperature": 24,
        "defrost": True,
        "steering_wheel_heat": True,
        "steering_wheel_level": 2,
        "mirror_heat": True,
    })
    assert set(params) == {"air_condition", "steeringWheelHeatCtrl", "rearMirrorHeating"}
    assert params["air_condition"]["wshld"] == "1"
    assert params["steeringWheelHeatCtrl"] == {"enable": True, "level": 2}
    assert params["rearMirrorHeating"] == {"enable": True, "value": 1}


def test_prepare_car_never_forwards_unknown_keys():
    """O envelope é allow-listed: nada que o site mande passa direto para a nuvem."""
    params = connector.prepare_car_parameters({
        "climate": True,
        "seat_setting": {"driver": "3"},
        "syn_path": {"latitude": "1"},
        "qualquer_coisa": "x",
    })
    assert set(params) == {"air_condition"}


def test_prepare_car_maps_auto_to_the_wind_mode():
    """`wind` é o modo sem quente/frio no vocabulário da biblioteca."""
    for alias in ("auto", "generic", "nohotcold"):
        params = connector.prepare_car_parameters({"climate": True, "climate_mode": alias})
        assert params["air_condition"]["mode"] == "wind", alias


def test_prepare_car_requires_at_least_one_dimension():
    with pytest.raises(ValueError):
        connector.prepare_car_parameters({})
    with pytest.raises(ValueError):
        connector.prepare_car_parameters({"climate": False, "mirror_heat": False})


@pytest.mark.parametrize(
    "parameters",
    [
        {"climate": True, "temperature": 15},
        {"climate": True, "temperature": 33},
        {"climate": True, "temperature": "quente"},
        {"climate": True, "wind_level": 0},
        {"climate": True, "wind_level": 8},
        {"climate": True, "climate_mode": "turbo"},
        {"steering_wheel_heat": True, "steering_wheel_level": 4},
    ],
)
def test_prepare_car_rejects_values_outside_the_documented_ranges(parameters):
    with pytest.raises(ValueError):
        connector.prepare_car_parameters(parameters)


def test_prepare_car_is_dispatched_with_the_built_envelope():
    client = ParityClient()
    connector.execute_vehicle_command(
        client.prepare_car, "prepare_car", "VIN", {"climate": True, "temperature": 21}
    )
    assert client.calls[0][0] == "prepare_car"
    assert client.calls[0][1]["params"]["air_condition"]["temperature"] == "21"


def test_prepare_car_requires_explicit_owner_confirmation():
    """Gate experimental: sem confirmação, nada de rede acontece."""
    with pytest.raises(ValueError) as excinfo:
        connector.handle_command({
            "credentials": {"operation_password": "000000"},
            "vehicle_id": "TESTVIN0000000001",
            "command": "prepare_car",
            "parameters": {"climate": True},
        })
    assert "confirmação explícita" in str(excinfo.value)
