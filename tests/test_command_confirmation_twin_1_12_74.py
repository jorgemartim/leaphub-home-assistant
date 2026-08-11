"""Contrato 1.12.74 — uma confirmação por comando, e ela chega a tempo.

Dois defeitos com a mesma origem: a confirmação do comando chegava tarde, e
chegava acompanhada de uma gêmea.

**1. A gêmea que nasce depois do veredito.** O Gateway arma a espera NOMEADA
sozinho, logo após o despacho, com o `request_id` do comando. O site repete o
boost depois, como sinal de recuperação. A 1.12.70 tornou o casamento simétrico,
mas só entre esperas PENDENTES: quando o boost repetido chega SEM id e a nomeada
já confirmou, não há nada pendente para adotar e nasce uma espera nova. Ela
confirma na primeira leitura — o estado que procura já foi atingido quando ela
nasce — e, enquanto vive, mantém a assinatura em cadência de comando, gastando
leituras da nuvem e trava de conta de que o comando SEGUINTE precisa.

Medido em campo em 11/08/2026, no log do Gateway:

    13:14:29  unlock (ref_…)           confirmado, 3 leituras, 21s
    13:14:37  unlock (sem request_id)  confirmado, 1 leitura,  0s   ← gêmea
    13:15:04  lock   (ref_163a7451)    confirmado, 3 leituras, 22s
    13:15:34  lock   (sem request_id)  confirmado, 2 leituras,  2s  ← gêmea

E o caso caro: a gêmea do `sunshade_open` das 13:16:11 nasceu às 13:17:21 — dois
segundos antes de o dono mandar FECHAR a cortina — gastou as 8 leituras do
orçamento em 111s procurando a cortina aberta, e encerrou "sem confirmação
conclusiva". O `windows_open` das 13:18:16, que dividia a mesma conta, morreu por
orçamento 230s depois.

A causa raiz é do site (ele descartava o `request_id` antes de mandar o boost, e
a 1.12.331 devolveu), mas o Gateway não pode depender da versão do site para não
duplicar trabalho. `_adopt_legacy_confirmation` já se protege exatamente disto
desde a 1.12.70; o `boost` não se protegia.

**2. A confirmação chegava depois de o carro retrancar sozinho.** O carro
retranca em ~30s. Com a escada antiga — 12s para a primeira releitura, +20s para
a segunda — o `unlock` despachado às 13:10:47 só foi confirmado às 13:11:45: 54s,
cinco leituras. A tela mostrou "destravado" quando o carro já tinha retrancado, e
segundos depois a leitura seguinte, essa fresca, disse "travado". A tela nunca
esteve errada; estava atrasada.

Nenhuma asserção fixa a versão exata nem copia a tupla da cadência.
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


if "leaphub_connector" not in sys.modules:
    load_module("leaphub_connector", APP / "connector.py")
telemetry = load_module("leaphub_telemetry_twin_1_12_74", APP / "telemetry_engine.py")

CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}

# O retravamento automático do carro. É ele que define o que "a tempo" quer
# dizer para o dono, e não nenhuma folga de rede.
RELOCK_HORIZON_SECONDS = 32


class Harness:
    """Motor com fila própria em disco temporário, sem tocar a rede."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-twin-")
        os.environ["LEAPHUB_TELEMETRY_DIR"] = self.tmp.name
        self.engine = telemetry.TelemetryEngine(
            {
                "telemetry_beta_enabled": True,
                "telemetry_beta_internal_url": "https://example.invalid/telemetry",
                "telemetry_background_enabled": True,
                # O valor que a instalação de campo guarda desde a 1.12.22. É de
                # propósito: o teto novo tem de valer SEM depender de a opção
                # ser reescrita, que é o que nunca acontece numa atualização.
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
            # Windows segura o handle do SQLite por um instante após o close.
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

    def command(
        self,
        sid: str,
        key: str,
        request_id: str | None,
        vehicle: str = "V1",
        seconds: int = 180,
    ) -> dict:
        context: dict[str, object] = {
            "command_key": key,
            "vehicle_remote_id": vehicle,
            "parameters": {},
        }
        if request_id is not None:
            context["request_id"] = request_id
        return self.engine.boost(sid, seconds=seconds, profile="command", context=context)

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

    def settle(self, sid: str, status: str = "confirmed", ago: float = 8.0) -> None:
        """Fecha as esperas pendentes como o ciclo de leitura fecharia."""
        resolution = "telemetry_match" if status == "confirmed" else "poll_budget"
        with self.engine.lock, self.engine._db() as db:
            db.execute(
                "UPDATE command_confirmations SET status=?,resolution=?,resolved_at=?,updated_at=? "
                "WHERE subscription_id=? AND status='pending'",
                (status, resolution, time.time() - ago, telemetry.utc_iso(), sid),
            )


# ---------------------------------------------------------------------------
# 1. Um comando físico, um veredito — e nenhuma espera depois dele.
# ---------------------------------------------------------------------------


def test_anonymous_boost_after_the_verdict_does_not_create_a_twin() -> None:
    """O caso de campo das 13:14:29 → 13:14:37."""
    with Harness() as h:
        sid = h.subscribe()

        # O Gateway arma a espera nomeada no despacho, e o ciclo a confirma.
        armada = h.command(sid, "unlock", "req-destravar")
        assert armada["pending_confirmations"] == 1
        h.settle(sid, "confirmed")
        assert h.pending(sid) == []

        # Agora chega o boost repetido do site, sem id — um site anterior à
        # 1.12.331, ou qualquer repetição que perca o id no caminho.
        repetido = h.command(sid, "unlock", None)

        assert h.pending(sid) == [], (
            "nasceu uma espera nova para um comando que já tem veredito; é ela que "
            "confirma na primeira leitura e come o orçamento do comando seguinte"
        )
        assert repetido["confirmation_window_reused"] is True, (
            "o Gateway tratou a repetição como comando novo"
        )
        assert repetido["pending_confirmations"] == 0
        # E não sobrou linha extra na tabela: a repetição não escreveu nada.
        assert len(h.rows(sid)) == 1


def test_the_twin_would_have_starved_the_next_command() -> None:
    """O custo que a gêmea cobrava: a conta fica em cadência de comando à toa.

    Com a gêmea pendente, `effective_command_mode` continua verdadeiro e a
    assinatura mantém a escada curta contra a nuvem por toda a janela — foi isso
    que sobrou para o `windows_open` das 13:18:16.
    """
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "sunshade_open", "req-cortina")
        h.settle(sid, "confirmed")

        h.command(sid, "sunshade_open", None)  # a repetição sem id
        # Nada pendente ⇒ o ciclo sai do modo comando sozinho.
        assert h.pending(sid) == []

        # E o comando SEGUINTE, que é outro comando de verdade, arma normalmente.
        seguinte = h.command(sid, "sunshade_close", "req-fechar")
        assert seguinte["pending_confirmations"] == 1
        pendentes = h.pending(sid)
        assert len(pendentes) == 1
        assert str(pendentes[0]["command_key"]) == "sunshade_close"


# ---------------------------------------------------------------------------
# 2. Controles negativos: a guarda não pode engolir recuperação legítima.
# ---------------------------------------------------------------------------


def test_an_inconclusive_window_can_still_be_rearmed() -> None:
    """Veredito NÃO é o mesmo que janela esgotada.

    Quando a janela fecha sem concluir, o boost do site é recuperação de verdade
    e tem de armar. Suprimi-lo deixaria o comando sem veredito para sempre — o
    oposto do que este contrato existe para comprar.
    """
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "trunk_open", "req-portamalas")
        h.settle(sid, "exhausted")
        assert h.pending(sid) == []

        recuperado = h.command(sid, "trunk_open", None)
        assert recuperado["pending_confirmations"] == 1, (
            "a guarda engoliu a rearmação de uma janela que fechou sem concluir"
        )
        assert len(h.pending(sid)) == 1


def test_an_old_verdict_does_not_suppress_a_new_command() -> None:
    """O dono pode mandar o mesmo comando de novo cinco minutos depois."""
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "lock", "req-trancar")
        # Veredito bem mais antigo que a janela que o boost está pedindo.
        h.settle(sid, "confirmed", ago=1800.0)

        de_novo = h.command(sid, "lock", None, seconds=180)
        assert de_novo["pending_confirmations"] == 1, (
            "um veredito de meia hora atrás bloqueou um comando novo"
        )


def test_an_identified_boost_is_never_suppressed() -> None:
    """A guarda é só para o boost anônimo; com id, quem manda é a 1.12.62."""
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "lock", "req-primeiro")
        h.settle(sid, "confirmed")

        outro = h.command(sid, "lock", "req-segundo")
        assert outro["confirmation_window_reused"] is False
        assert outro["pending_confirmations"] == 1


def test_the_site_armed_path_still_works_without_the_gateway_arm() -> None:
    """CONTROLE: sem nenhuma espera anterior, o boost sem id continua armando.

    É o caminho de quando o arme interno do Gateway falha
    (`confirmation_armed_by_gateway=False`) e o site é a única rede.
    """
    with Harness() as h:
        sid = h.subscribe()
        sozinho = h.command(sid, "windows_open", None)
        assert sozinho["pending_confirmations"] == 1
        assert len(h.pending(sid)) == 1


def test_a_different_vehicle_is_a_different_command() -> None:
    with Harness() as h:
        sid = h.subscribe(vehicles=("V1", "V2"))
        h.command(sid, "lock", "req-v1", vehicle="V1")
        h.settle(sid, "confirmed")

        outro_carro = h.command(sid, "lock", None, vehicle="V2")
        assert outro_carro["pending_confirmations"] == 1, (
            "o veredito de um carro suprimiu a espera do outro"
        )


# ---------------------------------------------------------------------------
# 3. A confirmação chega antes de o carro retrancar sozinho.
# ---------------------------------------------------------------------------


def test_first_reread_lands_before_the_car_relocks_itself() -> None:
    with Harness() as h:
        cadencia = list(h.engine.command_cadence)
        teto = telemetry.TelemetryEngine.COMMAND_FIRST_POLL_CEILING_SECONDS

        # O teto é de CÓDIGO: a instalação de campo guarda 12 na opção e nunca
        # releria um padrão novo do config.yaml. Este harness usa 12 de
        # propósito, e a escada tem de sair abaixo dele mesmo assim.
        assert h.engine.command_seconds >= teto
        assert cadencia[0] <= teto, (
            f"a primeira releitura saiu em {cadencia[0]}s; a opção legada venceu o teto"
        )
        assert teto <= 10, "o teto deixou de ser um teto útil"

        acumulada = [0]
        for passo in cadencia[:-1]:
            acumulada.append(acumulada[-1] + passo)

        dentro = sum(1 for instante in acumulada if instante <= RELOCK_HORIZON_SECONDS)
        assert dentro >= 4, (
            f"apenas {dentro} leituras caem nos primeiros {RELOCK_HORIZON_SECONDS}s; "
            "a confirmação volta a descrever um estado que o carro já desfez"
        )

        # E a escada não pode ter virado laço apertado contra a nuvem: o
        # orçamento total de leituras é o mesmo, só distribuído mais cedo.
        assert h.engine.command_max_polls <= telemetry.TelemetryEngine.COMMAND_MAX_POLLS_CEILING
        assert all(passo >= 5 for passo in cadencia)


def test_the_ladder_still_covers_the_whole_window() -> None:
    """Antecipar as primeiras leituras não pode deixar o fim da janela cego."""
    with Harness() as h:
        cadencia = list(h.engine.command_cadence)
        orcamento = h.engine.command_max_polls
        assert len(cadencia) >= orcamento

        cobertura = sum(cadencia[: orcamento - 1])
        assert cobertura >= 180, (
            f"{orcamento} leituras cobrem apenas {cobertura}s dos 180s da janela"
        )

        # CONTROLE DE REGRESSÃO contra a escada antiga: ela também cobria os
        # 180s, mas com os dois últimos degraus FORA da janela, onde
        # `_within_command_window` tinha de encurtá-los. A nova cabe.
        acumulada = [0]
        for passo in cadencia[:-1]:
            acumulada.append(acumulada[-1] + passo)
        assert sum(1 for instante in acumulada if instante <= 180) >= orcamento - 1, (
            "degraus demais caem fora da janela e dependem de encurtamento para existir"
        )


# ---------------------------------------------------------------------------
# 4. A guarda mora no lugar certo.
# ---------------------------------------------------------------------------


def test_the_guard_lives_in_the_boost_path_and_only_for_positive_verdicts() -> None:
    """Alvo é condição derivada; a asserção exercita a derivação.

    O ponto não é qual linha implementa: é que a supressão seja condicional à
    AUSÊNCIA de id e ao veredito ser positivo. Uma guarda incondicional aqui
    calaria a recuperação, que é o defeito oposto e pior.
    """
    fonte = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("def _settled_confirmation"):]
    corpo = corpo[: corpo.index("def _register_confirmation")]

    assert "status='confirmed'" in corpo, (
        "a guarda passou a suprimir também janela esgotada, e a recuperação morre com ela"
    )
    assert "resolved_at>=" in corpo, "a guarda deixou de ter limite de tempo"

    registro = fonte[fonte.index("def _register_confirmation"):]
    registro = registro[: registro.index("def _prune_confirmations")]
    assert "if not request_id:" in registro, (
        "a supressão deixou de depender da ausência de request_id"
    )
    assert registro.index("_match_pending_confirmation(") < registro.index("_settled_confirmation("), (
        "a espera PENDENTE tem de ser procurada primeiro; senão a adoção da 1.12.62 morre"
    )
