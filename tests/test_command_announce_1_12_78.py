"""Contrato 1.12.78 — o Gateway ANUNCIA o fim do comando; o site não espera o cron.

MEDIDO ao vivo em 12/08/2026, conta acct_1c8b987d, comando `unlock`:

    09:21:25    site despacha; Gateway aceita (POST /v1/vehicles/command -> 200)
    ~09:21:28   o carro destrava fisicamente (~3 s, com o dono à vista)
    09:21:31,9  worker TERMINA: dispatch=6171ms, total=6180ms,
                ack=library_returned, resultado_remoto=completed, sinal=positive
    09:22:07    site ainda stage: executing, cloud_accepted: false
    09:22:31    site enfim stage: sent, cloud_accepted: true

Carro 3 s, Gateway 6,2 s, site 41-65 s. O navegador perguntava a cada 4-6 s e
recebeu `executing` em TODAS as ~10 vezes: não havia o que ler, porque o
desfecho existia só dentro do Gateway até o ciclo do cron do site vir buscá-lo.

Este contrato fixa o atalho e, principalmente, o que ele NÃO pode fazer.

GARANTIAS, cada uma com o seu controle negativo:

  A. o anúncio vai para a rota de comando derivada da URL de telemetria já
     configurada, e é assinado PARA ESSE caminho — a mesma assinatura não vale
     para o caminho da telemetria (é o que o site confere);
  B. o anúncio não encosta na conexão da thread de entrega — usar aquele lock
     colocaria o anúncio atrás de um lote de telemetria, que é exatamente a
     fila que ele veio desfazer;
  C. o anúncio é melhor esforço: site sem a rota (404), erro de transporte ou
     destino fora do formato conhecido devolvem False sem levantar exceção,
     porque o ciclo do cron continua sendo a rede de segurança;
  D. o payload anunciado é o MESMO que `/v1/vehicles/command/status` devolveria
     — senão push e cron produziriam estados diferentes para o mesmo comando.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import importlib.util
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

STAGING_SECRET = "s" * 32
TELEMETRY_URL = "https://example.invalid/leap/api/internal/telemetry/events"
TELEMETRY_PATH = "/leap/api/internal/telemetry/events"
ANNOUNCE_PATH = "/leap/api/internal/commands/result"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_command_announce_test", APP / "telemetry_engine.py")


def new_engine(base: Path, url: str = TELEMETRY_URL):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    return telemetry.TelemetryEngine(
        {
            "telemetry_beta_enabled": True,
            "telemetry_beta_internal_url": url,
            "telemetry_production_enabled": False,
        },
        {"staging": STAGING_SECRET, "production": "p" * 32},
        threading.BoundedSemaphore(4),
    )


def close_engine(engine) -> None:
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


class _Response:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.will_close = False

    def read(self, _limit: int = 0) -> bytes:
        return b'{"ok": true, "matched": true, "applied": true}'

    def getheader(self, _name: str, default: str = "") -> str:
        return default


def _connection_factory(opened: list, status: int = 200, explode: bool = False):
    class _Connection:
        def __init__(self, host, port=None, **_kwargs) -> None:
            self.host = host
            self.port = port
            self.requests: list = []
            self.closed = False
            opened.append(self)

        def request(self, method, target, body=None, headers=None):
            if explode:
                raise http.client.RemoteDisconnected("Remote end closed connection without response")
            self.requests.append((method, target, body, dict(headers or {})))

        def getresponse(self):
            return _Response(status)

        def close(self) -> None:
            self.closed = True

    return _Connection


def signature_for(path: str, body: bytes, headers: dict) -> str:
    """Recalcula a assinatura do jeito que o site recalcula, para o caminho dado."""
    canonical = (
        f"POST\n{path}\n{headers['X-LeapHub-Timestamp']}\n"
        f"{headers['X-LeapHub-Nonce']}\n{hashlib.sha256(body).hexdigest()}"
    ).encode()
    return hmac.new(STAGING_SECRET.encode(), canonical, hashlib.sha256).hexdigest()


def announce(engine, opened: list, status: int = 200, explode: bool = False, result: dict | None = None) -> bool:
    original = telemetry.http.client.HTTPSConnection
    telemetry.http.client.HTTPSConnection = _connection_factory(opened, status=status, explode=explode)
    try:
        return engine.announce_command_result(
            "staging",
            "cmd-1234567890abcdef",
            result if result is not None else {"status": "sent", "ok": True, "remote_result_signal": "positive"},
        )
    finally:
        telemetry.http.client.HTTPSConnection = original


def test_announce_posts_to_the_command_route_signed_for_that_path():
    """A. o destino é derivado da telemetria, e a assinatura é do caminho do anúncio."""
    with tempfile.TemporaryDirectory(prefix="leaphub-announce-route-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            assert announce(engine, opened) is True
            assert len(opened) == 1
            method, target, body, headers = opened[0].requests[0]
            assert method == "POST"
            assert target == ANNOUNCE_PATH

            # O site confere a assinatura contra o caminho que ele mesmo serve.
            assert headers["X-LeapHub-Signature"] == signature_for(ANNOUNCE_PATH, body, headers)
            # Controle negativo: uma assinatura de telemetria não abriria esta
            # porta, nem a deste anúncio abriria a da telemetria.
            assert headers["X-LeapHub-Signature"] != signature_for(TELEMETRY_PATH, body, headers)

            sent = json.loads(body.decode("utf-8"))
            assert sent["request_id"] == "cmd-1234567890abcdef"
            assert sent["result"]["status"] == "sent"
        finally:
            close_engine(engine)


def test_announce_does_not_touch_the_delivery_connection():
    """B. o atalho não pode entrar na fila que ele veio desfazer."""
    with tempfile.TemporaryDirectory(prefix="leaphub-announce-lock-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            assert announce(engine, opened) is True
            # A conexão do lote de telemetria continua intocada: o anúncio abriu
            # a sua própria e a fechou.
            assert engine._delivery_connection is None
            assert opened[0].closed is True
        finally:
            close_engine(engine)


def test_announce_is_silent_when_the_site_has_no_route():
    """C. site anterior à rota responde 404 — é degradação, não erro."""
    with tempfile.TemporaryDirectory(prefix="leaphub-announce-404-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            assert announce(engine, opened, status=404) is False
            assert len(opened) == 1
        finally:
            close_engine(engine)


def test_announce_is_silent_when_the_transport_fails():
    """C. queda de rede não pode derrubar um worker que já concluiu o comando."""
    with tempfile.TemporaryDirectory(prefix="leaphub-announce-down-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            assert announce(engine, opened, explode=True) is False
            assert opened[0].closed is True
        finally:
            close_engine(engine)


def test_announce_refuses_a_destination_it_cannot_derive():
    """C. sem palpite de rota: destino fora do formato conhecido não é anunciado."""
    with tempfile.TemporaryDirectory(prefix="leaphub-announce-odd-") as tmp:
        engine = new_engine(Path(tmp), url="https://example.invalid/leap/api/outra/coisa")
        try:
            opened: list = []
            assert announce(engine, opened) is False
            assert opened == []
        finally:
            close_engine(engine)


def test_announce_needs_a_request_id_and_a_result():
    """C. anúncio vazio não vira requisição."""
    with tempfile.TemporaryDirectory(prefix="leaphub-announce-empty-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            opened: list = []
            original = telemetry.http.client.HTTPSConnection
            telemetry.http.client.HTTPSConnection = _connection_factory(opened)
            try:
                assert engine.announce_command_result("staging", "", {"status": "sent"}) is False
                assert engine.announce_command_result("staging", "cmd-1234567890abcdef", {}) is False
            finally:
                telemetry.http.client.HTTPSConnection = original
            assert opened == []
        finally:
            close_engine(engine)


def test_announced_payload_is_what_the_status_route_would_return(tmp_path):
    """D. uma única fonte do payload: push e cron não podem divergir."""
    os.environ["LEAPHUB_OPTIONS_PATH"] = str(tmp_path / "options.json")
    (tmp_path / "options.json").write_text('{"staging_secret":"' + "x" * 32 + '"}')
    os.environ["LEAPHUB_COMMAND_DB_PATH"] = str(tmp_path / "commands.sqlite")
    os.environ["LEAPHUB_NONCE_DB_PATH"] = str(tmp_path / "nonces.sqlite")
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(tmp_path / "telemetry")

    load_module("leaphub_privacy", APP / "privacy.py")
    load_module("leaphub_connection_orchestrator", APP / "connection_orchestrator.py")
    load_module("leaphub_event_transport", APP / "event_transport.py")
    load_module("leaphub_connector", APP / "connector.py")
    load_module("leaphub_telemetry_engine", APP / "telemetry_engine.py")
    server = load_module("connector_server_announce_178", APP / "connector_server.py")
    server.initialize_command_db()

    request_id = "cmd-abcdef1234567890"
    # O diário deriva o hash exatamente assim; é a chave que a rota de status usa.
    request_hash = hashlib.sha256(f"staging|{request_id}".encode("utf-8")).hexdigest()

    announced = server.command_journal_finish(
        request_hash,
        request_id,
        {"verified_by_gateway": False, "remote_result_signal": "positive", "message": "ok"},
    )
    assert isinstance(announced, dict)

    # `command_journal_status` é o que responde `/v1/vehicles/command/status`.
    served = server.command_journal_status("staging", {"request_id": request_id})
    assert served.get("status") != "unknown", "o diário não localizou o comando recém-concluído"

    for field in ("status", "ok", "accepted", "queued", "confirmation_pending", "vehicle_confirmed", "request_id"):
        assert announced[field] == served[field], f"{field} divergiu entre anúncio e consulta"
    # E o desfecho medido em campo continua sendo o que o site recebe.
    assert announced["status"] == "sent"
    assert announced["remote_result_signal"] == "positive"


def test_journal_finish_without_hash_announces_nothing(tmp_path):
    """D. sem diário não há payload — e sem payload não há anúncio."""
    os.environ["LEAPHUB_OPTIONS_PATH"] = str(tmp_path / "options.json")
    (tmp_path / "options.json").write_text('{"staging_secret":"' + "x" * 32 + '"}')
    os.environ["LEAPHUB_COMMAND_DB_PATH"] = str(tmp_path / "commands2.sqlite")
    os.environ["LEAPHUB_NONCE_DB_PATH"] = str(tmp_path / "nonces2.sqlite")
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(tmp_path / "telemetry2")

    load_module("leaphub_privacy", APP / "privacy.py")
    load_module("leaphub_connection_orchestrator", APP / "connection_orchestrator.py")
    load_module("leaphub_event_transport", APP / "event_transport.py")
    load_module("leaphub_connector", APP / "connector.py")
    load_module("leaphub_telemetry_engine", APP / "telemetry_engine.py")
    server = load_module("connector_server_announce_178_b", APP / "connector_server.py")
    server.initialize_command_db()

    assert server.command_journal_finish(None, "cmd-abcdef1234567890", {"ok": True}) is None

    calls: list = []
    server.TELEMETRY.announce_command_result = lambda *args: calls.append(args) or True
    server.announce_command_result_async("staging", "cmd-abcdef1234567890", None)
    assert calls == []
