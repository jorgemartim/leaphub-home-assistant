"""Contrato 1.12.52 — o keep-alive da entrega precisa ser ciente do servidor.

A 1.12.51 passou a reaproveitar a conexão TLS entre lotes, mas `http.client`
não verifica se o socket do pool continua aberto: ele escreve a requisição e só
descobre no `getresponse()`. Na hospedagem compartilhada a conexão ociosa é
fechada em poucos segundos, enquanto os lotes saem a cada 20-120s — então quase
toda entrega reaproveitada falhava com `RemoteDisconnected` antes de o PHP do
site executar, e o lote voltava para o backoff.
"""

from __future__ import annotations

import http.client
import importlib.util
import os
import sys
import tempfile
import threading
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
telemetry = load_module("leaphub_telemetry_keepalive_test", APP / "telemetry_engine.py")


def new_engine(base: Path):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    return telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": "https://example.invalid/telemetry",
            "telemetry_production_enabled": False,
        },
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(4),
    )


def close_engine(engine) -> None:
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


class _Response:
    def __init__(self, keep_alive: str = "") -> None:
        self.status = 200
        self.will_close = False
        self._keep_alive = keep_alive

    def read(self, _limit: int) -> bytes:
        return b'{"ok": true, "results": []}'

    def getheader(self, name: str, default: str = "") -> str:
        return self._keep_alive if name.lower() == "keep-alive" else default


def _connection_factory(opened: list, keep_alive: str = "", fail_first_reuse: bool = False):
    class _Connection:
        def __init__(self, *_args, **_kwargs) -> None:
            self.requests: list = []
            self.closed = False
            opened.append(self)

        def request(self, method, target, body=None, headers=None):
            self.requests.append((method, target, dict(headers or {})))
            if fail_first_reuse and len(self.requests) > 1:
                raise http.client.RemoteDisconnected("Remote end closed connection without response")

        def getresponse(self):
            return _Response(keep_alive)

        def close(self) -> None:
            self.closed = True

    return _Connection


def _sign_factory(nonces: list):
    def sign() -> dict:
        nonce = f"nonce-{len(nonces)}"
        nonces.append(nonce)
        return {"X-LeapHub-Nonce": nonce}

    return sign


def test_idle_connection_is_not_reused_beyond_the_keep_alive_window():
    """O bug de campo: reaproveitar depois da janela escreve num socket morto."""
    with tempfile.TemporaryDirectory(prefix="leaphub-keepalive-idle-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            original = telemetry.http.client.HTTPSConnection
            telemetry.http.client.HTTPSConnection = _connection_factory(opened)
            try:
                url = "https://example.invalid/leap/api/internal/telemetry/events"
                engine._post_delivery(url, {"X-Test": "1"}, b"{}")
                # Dentro da janela a conexão continua valendo.
                engine._post_delivery(url, {"X-Test": "2"}, b"{}")
                assert len(opened) == 1
                # Um lote depois da janela precisa abrir conexão nova.
                engine._delivery_connection_idle_since -= engine._delivery_idle_max + 1.0
                engine._post_delivery(url, {"X-Test": "3"}, b"{}")
                assert len(opened) == 2
                assert opened[0].closed is True
            finally:
                telemetry.http.client.HTTPSConnection = original
                engine._close_delivery_connection()
        finally:
            close_engine(engine)


def test_reused_connection_failure_retries_once_with_a_new_signature():
    """A queda do socket reaproveitado não pode custar um ciclo de backoff."""
    with tempfile.TemporaryDirectory(prefix="leaphub-keepalive-retry-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            nonces: list = []
            original = telemetry.http.client.HTTPSConnection
            telemetry.http.client.HTTPSConnection = _connection_factory(opened, fail_first_reuse=True)
            try:
                url = "https://example.invalid/leap/api/internal/telemetry/events"
                sign = _sign_factory(nonces)
                first = engine._post_delivery(url, sign(), b"{}", sign=sign)
                assert first == {"ok": True, "results": []}
                # Segunda entrega: a conexão do pool cai e a nova precisa entregar.
                second = engine._post_delivery(url, sign(), b"{}", sign=sign)
                assert second == {"ok": True, "results": []}
                assert len(opened) == 2, "a repetição precisa usar conexão nova"
                assert opened[0].closed is True
                # Nonce repetido seria recusado pelo site como requisição repetida.
                assert len(nonces) == len(set(nonces))
                assert opened[1].requests[0][2]["X-LeapHub-Nonce"] != opened[0].requests[-1][2]["X-LeapHub-Nonce"]
            finally:
                telemetry.http.client.HTTPSConnection = original
                engine._close_delivery_connection()
        finally:
            close_engine(engine)


def test_without_sign_there_is_no_retry():
    """Sem como renovar o nonce, repetir seria recusado — mantém uma tentativa."""
    with tempfile.TemporaryDirectory(prefix="leaphub-keepalive-nosign-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            original = telemetry.http.client.HTTPSConnection
            telemetry.http.client.HTTPSConnection = _connection_factory(opened, fail_first_reuse=True)
            try:
                url = "https://example.invalid/leap/api/internal/telemetry/events"
                engine._post_delivery(url, {"X-Test": "1"}, b"{}")
                raised = False
                try:
                    engine._post_delivery(url, {"X-Test": "2"}, b"{}")
                except http.client.RemoteDisconnected:
                    raised = True
                assert raised
                assert len(opened) == 1
                assert engine._delivery_connection is None
            finally:
                telemetry.http.client.HTTPSConnection = original
                engine._close_delivery_connection()
        finally:
            close_engine(engine)


def test_server_keep_alive_timeout_narrows_the_reuse_window():
    """Quando o servidor anuncia a janela, ela vale — com margem de um segundo."""
    with tempfile.TemporaryDirectory(prefix="leaphub-keepalive-window-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            original = telemetry.http.client.HTTPSConnection
            telemetry.http.client.HTTPSConnection = _connection_factory(opened, keep_alive="timeout=3, max=100")
            try:
                url = "https://example.invalid/leap/api/internal/telemetry/events"
                engine._post_delivery(url, {"X-Test": "1"}, b"{}")
                assert engine._delivery_idle_max == 2.0
            finally:
                telemetry.http.client.HTTPSConnection = original
                engine._close_delivery_connection()

            # O anúncio nunca ultrapassa os limites de segurança do motor.
            engine._delivery_idle_max = telemetry.DELIVERY_IDLE_DEFAULT_SECONDS
            engine._remember_delivery_idle_window("timeout=999")
            assert engine._delivery_idle_max == telemetry.DELIVERY_IDLE_MAX_SECONDS
            engine._remember_delivery_idle_window("timeout=0")
            assert engine._delivery_idle_max == telemetry.DELIVERY_IDLE_MIN_SECONDS
            engine._remember_delivery_idle_window("")
            assert engine._delivery_idle_max == telemetry.DELIVERY_IDLE_MIN_SECONDS
        finally:
            close_engine(engine)


def test_delivery_signs_every_attempt():
    """A assinatura por tentativa é o que torna a repetição possível."""
    source = (Path(__file__).resolve().parents[1] / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
    assert "def sign_headers() -> dict[str, str]:" in source
    assert "payload = self._post_delivery(url, headers, body, sign=sign_headers)" in source
    assert 'ENGINE_VERSION = "1.12.58"' in source
