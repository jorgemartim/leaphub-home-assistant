"""Contrato 1.12.53 — a renovação de sessão precisa achar o método real.

`_try_refresh_client_session` procurava o método por `refresh_session`,
`refresh_token` e `refresh`. Na `leapmotor-api` ele se chama `token_refresh`.
Nenhum dos três existia, `getattr` devolvia `None` para todos e a renovação
nunca acontecia: toda sessão vencida caía no login completo, de 5 a 18 s por
conta.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_session_refresh_test", APP / "telemetry_engine.py")


class _TokenRefreshClient:
    """Só expõe o nome real da biblioteca."""

    def __init__(self, result: bool = True) -> None:
        self.calls = 0
        self._result = result

    def token_refresh(self) -> bool:
        self.calls += 1
        return self._result


class _LegacyClient:
    """Versões antigas usavam outro nome; a cadeia não pode perdê-las."""

    def __init__(self) -> None:
        self.calls = 0

    def refresh_session(self) -> bool:
        self.calls += 1
        return True


class _AliasedClient:
    """Mesma implementação sob dois nomes: uma chamada só à nuvem."""

    def __init__(self) -> None:
        self.calls = 0

    def token_refresh(self) -> bool:
        self.calls += 1
        return True

    refresh = token_refresh


def test_token_refresh_is_the_first_alias_tried():
    client = _TokenRefreshClient()
    assert telemetry.TelemetryEngine._try_refresh_client_session(client) is True
    assert client.calls == 1, "token_refresh precisa ser chamado"


def test_legacy_alias_still_works():
    client = _LegacyClient()
    assert telemetry.TelemetryEngine._try_refresh_client_session(client) is True
    assert client.calls == 1


def test_same_implementation_under_two_names_is_called_once():
    client = _AliasedClient()
    telemetry.TelemetryEngine._try_refresh_client_session(client)
    assert client.calls == 1, "aliases da mesma função não podem multiplicar chamadas"


def test_client_without_any_refresh_does_not_break():
    class _Bare:
        pass

    assert telemetry.TelemetryEngine._try_refresh_client_session(_Bare()) is False


def test_alias_chain_declares_the_real_method_name():
    source = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    assert '"token_refresh", "refresh_session", "refresh_token", "refresh"' in source
    assert 'ENGINE_VERSION = "1.12.56"' in source
