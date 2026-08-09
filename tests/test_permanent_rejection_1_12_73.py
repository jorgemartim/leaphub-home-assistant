"""Contrato 1.12.73 — recusa permanente sai da fila; a fila desiste sozinha.

MEDIDO em 09/08/2026, no log deste Gateway contra o site na 1.12.327:

    06:04:33 WARNING Entrega de 1 evento(s) adiada: O site recusou parte do lote.
    ...      a cada ~2 min, sempre "1 evento"
    12:48:36 WARNING Entrega de 1 evento(s) adiada: O site recusou parte do lote.

E, do outro lado, o `error_log` do site apontando o MESMO evento o tempo todo:

    Evento de telemetria recusado (ref_a26eceeb): O veículo da telemetria ainda
    não foi confirmado nesta conta.

Sete horas, um único evento preso, ~700 tentativas por dia. Três coisas se
somavam:

  1. o site respondia só "recusado" e `_deliver_group` lia isso como "adiar";
  2. o backoff de `_delivery_failed` tem teto de 120 s, então a repetição nunca
     desacelerava;
  3. a retenção só apagava evento ENTREGUE, então o não entregue não envelhecia.

Esta release fecha (1) com a marca que o site passou a mandar na 1.12.328, e
fecha (3) sozinha — sem depender de site nenhum. (2) continua como está: para
falha transitória, repetir rápido é o comportamento certo.

GARANTIAS, e cada uma com o controle negativo do lado:

  A. evento marcado `permanent` sai da fila (status 'failed'), com o motivo
     gravado — e um evento SEM a marca continua sendo adiado, que é o que um
     site antigo produz;
  B. evento pendente que passa da janela de retenção é abandonado pela própria
     fila — e um evento recente NÃO é;
  C. o que já é terminal e velho sai do disco, entregue ou descartado — senão o
     descarte só trocaria repetição infinita por linha infinita.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
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
telemetry = load_module("leaphub_telemetry_permanent_rejection_test", APP / "telemetry_engine.py")


def new_engine(base: Path, options: dict | None = None):
    os.environ["LEAPHUB_TELEMETRY_DIR"] = str(base)
    merged = {
        "telemetry_beta_enabled": True,
        "telemetry_beta_internal_url": "https://example.invalid/leap/api/internal/telemetry/events",
        "telemetry_production_enabled": False,
    }
    merged.update(options or {})
    return telemetry.TelemetryEngine(
        merged,
        {"staging": "s" * 32, "production": "p" * 32},
        threading.BoundedSemaphore(4),
    )


def close_engine(engine) -> None:
    engine.close_storage()
    if engine._instance_lock_handle is not None:
        engine._instance_lock_handle.close()


def payload(account: int = 150) -> dict:
    return {
        "subscription_id": f"leaphub-staging-account-{account}",
        "account_id": account,
        "credentials": {
            "email": f"tester{account}@example.invalid",
            "password": "not-a-real-password",
            "certificate_pem": "certificate",
            "private_key_pem": "private-key",
        },
        "vehicle_ids": [f"vehicle-{account}"],
        "enabled": True,
    }


def seed_event(engine, event_id: str, *, created_at: str | None = None, status: str = "pending",
               delivered_at: str | None = None, account: int = 150) -> None:
    """Põe um evento na fila com a idade e o estado que o cenário pede."""
    with engine.lock, engine._db() as db:
        db.execute(
            "INSERT INTO events(event_id,subscription_id,environment,account_id,remote_id,source_at,"
            "payload_encrypted,payload_hash,status,attempts,next_attempt_at,created_at,delivered_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                payload(account)["subscription_id"],
                "staging",
                account,
                f"vehicle-{account}",
                telemetry.utc_iso(),
                engine.fernet.encrypt(json.dumps({"remote_id": f"vehicle-{account}"}).encode()),
                "h" * 64,
                status,
                0,
                time.time() - 1,
                created_at or telemetry.utc_iso(),
                delivered_at,
            ),
        )


def pending_rows(engine) -> list:
    with engine.lock, engine._db() as db:
        return db.execute("SELECT * FROM events WHERE status='pending' ORDER BY event_id").fetchall()


def state_of(engine, event_id: str) -> tuple[str, str, int]:
    with engine.lock, engine._db() as db:
        row = db.execute("SELECT status,last_error,attempts FROM events WHERE event_id=?", (event_id,)).fetchone()
    if row is None:
        return ("AUSENTE", "", -1)
    return (str(row["status"]), str(row["last_error"] or ""), int(row["attempts"]))


def dias_atras(dias: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat().replace("+00:00", "Z")


def deliver_with_response(engine, resposta: dict) -> list:
    """Roda `_deliver_group` com a resposta do site trocada por uma de mentira.

    Só o transporte é dublado. A decisão sobre cada evento — entregar, adiar ou
    descartar — continua sendo a do código sob teste.
    """
    registrado: list[str] = []
    original_post = engine._post_delivery
    original_warning = telemetry.LOG.warning

    def fake_post(*_args, **_kwargs):
        return resposta

    def capture(mensagem, *args):
        registrado.append(str(mensagem) % args if args else str(mensagem))

    engine._post_delivery = fake_post
    telemetry.LOG.warning = capture
    try:
        engine._deliver_group("staging", pending_rows(engine))
    finally:
        engine._post_delivery = original_post
        telemetry.LOG.warning = original_warning
    return registrado


# ---------------------------------------------------------------- GARANTIA A
def test_permanent_rejection_leaves_the_queue():
    """O caso do dono: o site diz que não adianta insistir, e a fila obedece."""
    with tempfile.TemporaryDirectory(prefix="leaphub-permanent-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            permanente = "a" * 64
            transitorio = "b" * 64
            seed_event(engine, permanente)
            seed_event(engine, transitorio)

            registrado = deliver_with_response(engine, {
                "ok": False,
                "failed": 2,
                "permanent_failures": 1,
                "results": [
                    {"event_id": permanente, "ok": False, "permanent": True,
                     "message": "O veículo da telemetria ainda não foi confirmado nesta conta."},
                    {"event_id": transitorio, "ok": False, "permanent": False,
                     "message": "SQLSTATE[HY000] [2002] No such file or directory"},
                ],
            })

            status, motivo, _ = state_of(engine, permanente)
            assert status == "failed", f"o evento permanente continua na fila como {status}"
            assert "não foi confirmado" in motivo, motivo

            # CONTROLE NEGATIVO: a recusa transitória NÃO pode sair da fila.
            # Sem esta metade, "descartar tudo o que falha" passaria — e a
            # primeira lentidão da hospedagem viraria perda de telemetria.
            status_transitorio, _, tentativas = state_of(engine, transitorio)
            assert status_transitorio == "pending", status_transitorio
            assert tentativas == 1, tentativas

            # O motivo do descarte aparece no log: quem lê "1 evento
            # descartado" precisa saber por quê sem abrir o banco.
            assert any("descartada em definitivo" in linha for linha in registrado), registrado
            assert any("não foi confirmado" in linha for linha in registrado), registrado
        finally:
            close_engine(engine)


def test_missing_mark_is_still_retried():
    """Site antigo não manda a marca — e nada pode mudar para ele.

    Este é o controle que impede a leitura preguiçosa de `permanent`: qualquer
    coisa que não seja exatamente `True` significa "tente de novo".
    """
    with tempfile.TemporaryDirectory(prefix="leaphub-sem-marca-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            sem_marca = "c" * 64
            marca_textual = "d" * 64
            seed_event(engine, sem_marca)
            seed_event(engine, marca_textual)

            deliver_with_response(engine, {
                "ok": False,
                "results": [
                    {"event_id": sem_marca, "ok": False, "message": "recusado"},
                    # Uma marca que NÃO é o booleano `True` não vale: `"true"`,
                    # `1` ou `"yes"` são o que um proxy ou um site futuro
                    # poderiam mandar sem querer dizer isto.
                    {"event_id": marca_textual, "ok": False, "permanent": "true", "message": "recusado"},
                ],
            })

            assert state_of(engine, sem_marca)[0] == "pending"
            assert state_of(engine, marca_textual)[0] == "pending"
        finally:
            close_engine(engine)


# ---------------------------------------------------------------- GARANTIA B
def test_queue_gives_up_on_events_older_than_retention():
    """A metade que não depende do site: nada pendente vive para sempre.

    Mesmo com um site que nunca aprendeu a marcar recusa permanente, a fila
    para de tentar na mesma janela em que já descartava o entregue.

    O evento antigo termina AUSENTE, e não `failed`: na mesma passagem ele é
    abandonado e, já estando além da janela, podado. Isso é o certo — o que a
    release existe para acabar é a repetição, e o registro do abandono é a linha
    de log, que esta asserção também exige. O descarte por recusa permanente é
    outro caso: aquele nasce recente e fica no banco a janela inteira, como o
    `test_permanent_rejection_leaves_the_queue` mede.
    """
    with tempfile.TemporaryDirectory(prefix="leaphub-desiste-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            velho = "e" * 64
            recente = "f" * 64
            seed_event(engine, velho, created_at=dias_atras(engine.retention_days + 1))
            seed_event(engine, recente, created_at=dias_atras(engine.retention_days - 1))

            registrado: list[str] = []
            original_warning = telemetry.LOG.warning
            telemetry.LOG.warning = lambda m, *a: registrado.append(str(m) % a if a else str(m))
            try:
                engine._maintenance_last_at = 0.0
                engine._maintenance()
            finally:
                telemetry.LOG.warning = original_warning

            assert state_of(engine, velho)[0] != "pending", "a fila continua tentando entregar o evento antigo"
            # O abandono passou pela marcação, e não por uma exclusão cega: a
            # linha só sai quando o UPDATE de `pending` casa alguma coisa.
            assert any("desistiu de 1 evento" in linha for linha in registrado), registrado

            # CONTROLE NEGATIVO: o recente continua na fila, intacto. Uma janela
            # mal calculada — ou um "apague o que for velho" sem distinguir
            # estado — apareceria exatamente aqui.
            assert state_of(engine, recente)[0] == "pending", "a fila desistiu de um evento ainda dentro da janela"
        finally:
            close_engine(engine)


# ---------------------------------------------------------------- GARANTIA C
def test_retention_also_reaps_discarded_events():
    """Descarte não pode trocar repetição infinita por linha infinita."""
    with tempfile.TemporaryDirectory(prefix="leaphub-poda-") as tmp:
        engine = new_engine(Path(tmp))
        try:
            assert engine.upsert("staging", payload())["ok"] is True
            descartado_velho = "1" * 64
            descartado_recente = "2" * 64
            entregue_velho = "3" * 64
            seed_event(engine, descartado_velho, status="failed", created_at=dias_atras(engine.retention_days + 2))
            seed_event(engine, descartado_recente, status="failed", created_at=dias_atras(1))
            seed_event(engine, entregue_velho, status="delivered",
                       created_at=dias_atras(engine.retention_days + 2),
                       delivered_at=dias_atras(engine.retention_days + 2))

            engine._maintenance_last_at = 0.0
            engine._maintenance()

            assert state_of(engine, descartado_velho)[0] == "AUSENTE", "descarte antigo continua ocupando disco"
            assert state_of(engine, entregue_velho)[0] == "AUSENTE", "a poda do entregue regrediu"
            # CONTROLE NEGATIVO: descarte recente permanece, porque é ele que
            # explica ao dono o que aconteceu com a leitura.
            assert state_of(engine, descartado_recente)[0] == "failed", "o descarte recente sumiu antes da hora"
        finally:
            close_engine(engine)
