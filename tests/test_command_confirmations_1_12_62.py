"""Contrato 1.12.62 — cada comando recebe o seu próprio veredito.

Defeito corrigido: a janela de confirmação morava em colunas únicas da linha da
assinatura (`command_key`, `command_vehicle_id`, `command_context_json`,
`command_started_at`). Um segundo comando com chave diferente não era
`same_command_window` e sobrescrevia o contexto do primeiro — que então nunca
recebia veredito nenhum, nem confirmado nem inconclusivo, e deixava o botão do
site girando para sempre.

Evidência de campo (30/07/2026): `sunshade_open` às 13:34:40, `unlock` às
13:36:03, janela fechando às 13:37:38 com log de `unlock` apenas. Nenhuma linha
sobre o `sunshade_open` em lugar nenhum.

O segundo defeito, no mesmo caminho: `command_max_polls=5` esgotava a janela em
~112s com a cadência (12, 20, 35, 45, 60, ...), embora `command_until` desse
180s. O `unlock` daquele mesmo dia teve uma amostra a +89s e ainda assim foi
declarado inconclusivo — carro acordando não cabia no orçamento.

O que este contrato protege:

1. Dois comandos distintos geram duas esperas, cada uma com hora de partida,
   contexto e contagem próprios. Repetir o boost do mesmo comando continua
   reaproveitando a espera (o site repete como sinal de recuperação).
2. Uma leitura de telemetria é confrontada com TODAS as esperas pendentes.
3. Quem encerra a espera é o prazo da janela; a contagem de leituras é só teto
   de segurança, e o piso cobre os 180s.
4. Uma janela herdada da versão anterior é adotada, não perdida.
5. Espera abandonada (assinatura liberada, credencial exigida) é encerrada e não
   sobrevive para sempre consumindo ciclos.

Nenhuma asserção fixa a versão exata.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# O motor importa `leaphub_connector`; carregá-lo com esse nome aqui evita que
# este contrato dependa de outro teste tê-lo posto em `sys.modules` antes.
if "leaphub_connector" not in sys.modules:
    load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_confirmations_1_12_62", APP / "telemetry_engine.py")

CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    """Motor com fila própria em disco temporário, sem tocar a rede."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-confirmations-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/telemetry",
                "telemetry_background_enabled": True,
                "telemetry_command_seconds": 12,
            },
            {"staging": "s" * 32, "production": "p" * 32},
            threading.BoundedSemaphore(2),
        )

    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.engine.close_storage()
        if self.engine._instance_lock_handle is not None:
            self.engine._instance_lock_handle.close()
        try:
            self.tmp.cleanup()
        except (OSError, PermissionError):
            # Windows mantém o handle do SQLite por um instante após o close;
            # o diretório temporário some com o sistema.
            pass

    def subscribe(self, sid: str = "sub-1", vehicles: tuple[str, ...] = ("V1",)) -> str:
        self.engine.upsert(
            "staging",
            {
                "subscription_id": sid,
                "account_id": 1,
                "credentials": dict(CREDENTIALS),
                "vehicle_ids": list(vehicles),
                "enabled": True,
            },
        )
        return sid

    def command(self, sid: str, key: str, request_id: str, vehicle: str = "V1", seconds: int = 180) -> dict:
        return self.engine.boost(
            sid,
            seconds=seconds,
            profile="command",
            context={
                "command_key": key,
                "vehicle_remote_id": vehicle,
                "request_id": request_id,
                "parameters": {},
            },
        )

    def rows(self, sid: str) -> list:
        with self.engine.lock, self.engine._db() as db:
            return list(
                db.execute(
                    "SELECT * FROM command_confirmations WHERE subscription_id=? ORDER BY started_at ASC",
                    (sid,),
                ).fetchall()
            )

    def pending(self, sid: str) -> list:
        return [row for row in self.rows(sid) if str(row["status"]) == "pending"]


def vehicle_sample(remote_id: str = "V1", **telemetry_fields: object) -> dict:
    return {"remote_id": remote_id, "telemetry": dict(telemetry_fields)}


def test_second_command_does_not_erase_the_first() -> None:
    """O caso de campo: cortina e depois destravar, na mesma assinatura."""
    with Harness() as h:
        sid = h.subscribe()
        first = h.command(sid, "sunshade_open", "req-cortina")
        assert first["ok"] is True
        assert first["confirmation_window_reused"] is False
        assert first["pending_confirmations"] == 1

        second = h.command(sid, "unlock", "req-destravar")
        assert second["confirmation_window_reused"] is False
        assert second["pending_confirmations"] == 2

        pendentes = h.pending(sid)
        assert len(pendentes) == 2, "o segundo comando substituiu o primeiro em vez de somar"
        chaves = sorted(str(row["command_key"]) for row in pendentes)
        assert chaves == ["sunshade_open", "unlock"]

        # CONTROLE: o contexto do primeiro tem de continuar sendo o dele. Era
        # exatamente isto que a versão anterior sobrescrevia.
        cortina = [row for row in pendentes if str(row["command_key"]) == "sunshade_open"][0]
        assert "req-cortina" in str(cortina["context_json"])
        assert str(cortina["request_id"]) == "req-cortina"


def test_repeated_boost_reuses_the_same_wait() -> None:
    """O site repete o boost como recuperação; isso não pode duplicar a espera."""
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "sunshade_open", "req-cortina")
        repeated = h.command(sid, "sunshade_open", "req-cortina")
        assert repeated["confirmation_window_reused"] is True
        assert repeated["pending_confirmations"] == 1
        assert len(h.pending(sid)) == 1

        # Boost sem request_id adota a espera existente, como antes.
        adopted = h.engine.boost(
            sid,
            seconds=180,
            profile="command",
            context={"command_key": "sunshade_open", "vehicle_remote_id": "V1"},
        )
        assert adopted["confirmation_window_reused"] is True
        assert len(h.pending(sid)) == 1


def test_one_sample_is_confronted_with_every_pending_wait() -> None:
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "sunshade_open", "req-cortina")
        h.command(sid, "unlock", "req-destravar")

        # A telemetria traz o estado da tranca, mas não o da cortina — que é
        # justamente o campo que a nuvem nunca publica neste carro.
        vehicles = [vehicle_sample("V1", locked=False)]
        veredictos = {}
        for row in h.pending(sid):
            outcome = h.engine._evaluate_confirmation(row, vehicles, time.time())
            veredictos[str(row["command_key"])] = outcome

        assert veredictos["unlock"]["confirmed"] is True
        assert veredictos["sunshade_open"]["confirmed"] is False
        assert veredictos["sunshade_open"]["evaluable"] is False, (
            "sem o campo sunshade_open na telemetria, o matcher não pode ser conclusivo"
        )
        # Ambas foram avaliadas: nenhuma ficou sem análise por causa da outra.
        assert veredictos["unlock"]["evaluated_samples"] == 1
        assert veredictos["sunshade_open"]["evaluated_samples"] == 1
        assert "sunshade_open=ausente" in veredictos["sunshade_open"]["field_gaps"]

        now = time.time()
        with h.engine.lock, h.engine._db() as db:
            for outcome in veredictos.values():
                h.engine._persist_confirmation(db, outcome, now, "2026-07-30T13:37:38Z")

        estados = {str(row["command_key"]): str(row["status"]) for row in h.rows(sid)}
        assert estados["unlock"] == "confirmed"
        assert estados["sunshade_open"] == "pending", (
            "a espera inconclusiva tem de continuar aberta até o prazo, não sumir"
        )


def test_deadline_closes_the_window_not_the_poll_count() -> None:
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine

        # O piso do orçamento cobre a janela inteira com a cadência publicada.
        assert engine.command_max_polls >= 8
        cobertura = sum(engine.command_cadence[: engine.command_max_polls - 1])
        assert cobertura >= 180, (
            f"{engine.command_max_polls} leituras cobrem apenas {cobertura}s dos 180s da janela"
        )

        h.command(sid, "unlock", "req-destravar")
        row = h.pending(sid)[0]
        vehicles = [vehicle_sample("V1", climate_on=True)]  # não confirma unlock
        base = {key: row[key] for key in row.keys()}

        # CONTROLE DE REGRESSÃO: na quinta leitura, com a janela ainda aberta, a
        # espera continua. Era aqui que a versão anterior desistia.
        quinta = dict(base)
        quinta["poll_count"] = 4
        outcome = engine._evaluate_confirmation(quinta, vehicles, time.time())
        assert outcome["poll_count"] == 5
        assert outcome["exhausted"] is False, (
            "cinco leituras voltaram a encerrar a janela antes do prazo"
        )

        # Prazo vencido encerra, e diz que foi o prazo.
        vencida = dict(base)
        vencida["expires_at"] = time.time() - 1
        outcome = engine._evaluate_confirmation(vencida, vehicles, time.time())
        assert outcome["exhausted"] is True
        assert outcome["reason"] == "window_deadline"

        # O teto de leituras continua existindo, para cadência encurtada.
        estourada = dict(base)
        estourada["poll_count"] = engine.command_max_polls
        outcome = engine._evaluate_confirmation(estourada, vehicles, time.time())
        assert outcome["exhausted"] is True
        assert outcome["reason"] == "poll_budget"


def test_legacy_window_is_adopted_after_upgrade() -> None:
    """Comando em voo durante a atualização não pode perder o veredito."""
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine
        started = time.time() - 30
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET command_until=?, command_key=?, command_vehicle_id=?, "
                "command_context_json=?, command_poll_count=?, command_started_at=? WHERE subscription_id=?",
                (time.time() + 120, "trunk_open", "V1", '{"request_id":"req-antigo"}', 2, started, sid),
            )
            subscription = db.execute(
                "SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)
            ).fetchone()
            engine._adopt_legacy_confirmation(db, subscription, time.time())

        pendentes = h.pending(sid)
        assert len(pendentes) == 1
        adotada = pendentes[0]
        assert str(adotada["command_key"]) == "trunk_open"
        assert str(adotada["request_id"]) == "req-antigo"
        assert int(adotada["poll_count"]) == 2, "a contagem já gasta foi reiniciada"
        assert abs(float(adotada["started_at"]) - started) < 1.0, (
            "a hora de partida foi trocada pela hora da adoção; a frescura passaria a mentir"
        )

        # Adotar duas vezes não duplica.
        with engine.lock, engine._db() as db:
            subscription = db.execute(
                "SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)
            ).fetchone()
            engine._adopt_legacy_confirmation(db, subscription, time.time())
        assert len(h.pending(sid)) == 1


def test_wait_created_during_the_cloud_call_survives_the_cleanup() -> None:
    """Comando enviado enquanto a leitura anterior ainda estava na nuvem.

    A decisão de limpar as colunas vem do retrato da assinatura lido antes da
    chamada à nuvem, que leva segundos. Uma espera criada nesse intervalo tem
    prazo no futuro e não pode ser encerrada por uma decisão anterior a ela.
    """
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine

        # Espera antiga, já vencida: é ela que a limpeza deve encerrar.
        h.command(sid, "lock", "req-antigo", seconds=30)
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE command_confirmations SET expires_at=? WHERE subscription_id=?",
                (time.time() - 120, sid),
            )
        # Espera nova, criada durante a coleta.
        h.command(sid, "unlock", "req-novo", seconds=180)

        cycle_epoch = time.time()
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE command_confirmations SET status='expired',resolution='window_expired',resolved_at=?,updated_at=? "
                "WHERE subscription_id=? AND status='pending' AND expires_at<=?",
                (cycle_epoch, "2026-07-30T13:37:38Z", sid, cycle_epoch),
            )
            live = db.execute(
                "SELECT COUNT(*) AS total FROM command_confirmations "
                "WHERE subscription_id=? AND status='pending' AND expires_at>?",
                (sid, cycle_epoch),
            ).fetchone()

        assert int(live["total"]) == 1, "a espera recém-criada foi encerrada junto com a vencida"
        vivos = {str(row["command_key"]): str(row["status"]) for row in h.rows(sid)}
        assert vivos["lock"] == "expired"
        assert vivos["unlock"] == "pending"


def test_abandoned_wait_is_closed() -> None:
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine
        h.command(sid, "lock", "req-trancar", seconds=30)

        # A assinatura é liberada (o site fecha a aba, a credencial expira): as
        # colunas de comando são zeradas e ninguém mais visita esta espera.
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET command_until=0, command_key=NULL, command_context_json=NULL "
                "WHERE subscription_id=?",
                (sid,),
            )
            db.execute(
                "UPDATE command_confirmations SET expires_at=? WHERE subscription_id=?",
                (time.time() - 600, sid),
            )
            fechadas = engine._prune_confirmations(db, time.time())

        assert fechadas == 1
        assert h.pending(sid) == [], "espera abandonada sobreviveu e voltaria a consumir ciclos"
        assert str(h.rows(sid)[0]["resolution"]) == "window_abandoned"
