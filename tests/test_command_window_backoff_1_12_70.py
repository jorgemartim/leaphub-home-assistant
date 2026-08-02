"""Contrato 1.12.70 — a janela de confirmação não pode ser desperdiçada.

Três defeitos distintos, todos medidos nos logs do Gateway de 02/08/2026 entre
13:42 e 14:04, e todos com o mesmo sintoma para o dono: o porta-malas abriu e a
tela disse que falhou.

1. **O backoff da janela era o backoff de quem olha a tela.**
   `_transient_backoff(failures, fast_mode)` recebia `fast_mode`, que é
   `interactive or command_mode`. Um `Read timed out` durante a confirmação
   reagendava a leitura seguinte para 45s (site aberto) ou 120s (site fechado),
   numa janela que dura 180s e cuja cadência começa em 12s. Uma única falha
   consumia a janela. Campo: `trunk_close` despachado às 14:03:36, aceito pela
   nuvem às 14:03:38, `Read timed out` às 14:04:10 com "nova leitura em 45s",
   e nenhuma linha de confirmação para ele em lugar nenhum.

2. **Reagendamento que cai depois do prazo não confirma nada.** Qualquer atraso
   escolhido por outro motivo tinha de ser encurtado para caber no que resta da
   janela — senão a leitura chega quando a espera já foi encerrada por
   `window_deadline`.

3. **O mesmo comando ganhava DUAS esperas.** O casamento era assimétrico: boost
   sem `request_id` adotava a espera existente, mas boost COM `request_id` nunca
   adotava uma espera sem id. A gêmea anônima confirma na primeira leitura,
   porque o estado dela já está satisfeito quando ela nasce, e escreve
   "confirmado ... 1 comando(s) ainda aguardam" — que se lê como se o comando
   recém-despachado tivesse sido o confirmado. Campo, duas vezes com o mesmo
   desenho: 13:42:45 `sunshade_open` → 0 aguardam, 13:43:16 `trunk_open`
   despachado, 13:43:23 `sunshade_open` **(sem request_id)** confirmado → 1
   aguarda; e 14:03:08 / 14:03:36 / 14:03:43 com `sunshade_close` e
   `trunk_close`.

E um quarto, que é a origem física do primeiro: o cliente Leapmotor da sessão
persistente é o MESMO que despacha os comandos, e foi criado com o tempo limite
da telemetria (15s). O despacho de `sunshade_position` levou 12,686s medidos —
2,3s de folga. O tempo limite é do cliente, não da chamada, então ele tem de
servir ao consumidor mais exigente dos dois.

Nenhuma asserção fixa a versão exata, e nenhuma cita a expressão que hoje
implementa a garantia: todas exercitam a derivação.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
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
telemetry = load_module("leaphub_telemetry_window_1_12_70", APP / "telemetry_engine.py")

CREDENTIALS = {
    "email": "dono@example.invalid",
    "password": "segredo",
    "certificate_pem": "cert",
    "private_key_pem": "key",
}


class Harness:
    """Motor com fila própria em disco temporário, sem tocar a rede."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="leaphub-window-")
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


# ---------------------------------------------------------------------------
# 1. O backoff da janela de confirmação é dela, não o de quem olha a tela.
# ---------------------------------------------------------------------------


def test_confirmation_window_has_its_own_transient_backoff() -> None:
    engine = telemetry.TelemetryEngine
    cadencia_inicial = 12

    for falhas in (1, 2, 3):
        janela = engine._transient_backoff(falhas, True, command_mode=True)
        tela = engine._transient_backoff(falhas, True)
        fundo = engine._transient_backoff(falhas, False)

        assert janela < tela, (
            f"com {falhas} falha(s) a janela esperaria {janela}s, o mesmo balde da presença ({tela}s)"
        )
        assert janela < fundo

    # A primeira tentativa tem de caber na cadência que a janela publica: o
    # sentido do conserto é não perder leituras, não empurrá-las para fora.
    primeira = engine._transient_backoff(1, True, command_mode=True)
    assert primeira <= cadencia_inicial, (
        f"a primeira retentativa da janela ({primeira}s) já é mais lenta que a cadência ({cadencia_inicial}s)"
    )

    # CONTROLE NEGATIVO: o valor exato de campo. Com o backoff da presença, uma
    # janela de 180s cabia em três falhas; com o de fundo, em uma.
    assert engine._transient_backoff(1, True) == 45
    assert engine._transient_backoff(1, False) == 120
    assert sum(engine._transient_backoff(n, True, command_mode=True) for n in (1, 2, 3)) < 180, (
        "três falhas seguidas ainda esgotam a janela inteira"
    )


def test_backoff_growth_is_preserved_inside_the_window() -> None:
    """Encurtar não pode virar laço apertado contra a nuvem."""
    engine = telemetry.TelemetryEngine
    valores = [engine._transient_backoff(n, True, command_mode=True) for n in range(1, 7)]
    assert valores == sorted(valores), "o backoff da janela parou de crescer"
    assert valores[0] >= 5, "a primeira retentativa ficou agressiva demais"
    assert len(set(valores)) > 1


# ---------------------------------------------------------------------------
# 2. Nenhum reagendamento cai depois do prazo da janela.
# ---------------------------------------------------------------------------


def test_reschedule_never_lands_after_the_window_closes() -> None:
    with Harness() as h:
        engine = h.engine
        agora = time.time()

        # Restam 20s de janela e o backoff pediria 45s: a leitura chegaria com a
        # espera já encerrada por prazo, ou seja, nunca.
        encurtado = engine._within_command_window(45, agora + 20, agora)
        assert encurtado < 20, "a leitura seguinte ainda cairia depois do fim da janela"
        assert encurtado >= 2, "o encurtamento virou laço apertado contra a nuvem"

        # Cabendo na janela, o atraso escolhido é respeitado.
        assert engine._within_command_window(8, agora + 180, agora) == 8

        # Janela já vencida: não há o que preservar, e encurtar aqui só somaria
        # chamadas à nuvem por um veredito que ninguém espera mais.
        assert engine._within_command_window(300, agora - 1, agora) == 300
        assert engine._within_command_window(300, 0, agora) == 300


def test_failure_paths_clamp_to_the_window() -> None:
    """A garantia é do CAMINHO, não da função: os pontos de falha usam o limite.

    Alvo é condição derivada, então a asserção exercita a derivação e exige que
    ela não seja incondicional — em vez de citar a linha que hoje a implementa.
    """
    fonte = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("def _poll_subscription"):]
    corpo = corpo[: corpo.index("def _session_operation_lock")]

    # Todo reagendamento por FALHA dentro do ciclo passa pelo limite da janela.
    assert corpo.count("_within_command_window(") >= 3, (
        "algum caminho de falha do ciclo continua reagendando sem olhar o prazo da janela"
    )
    # A escolha do backoff DEPENDE do modo comando. Procurar a string
    # `command_mode=command_mode` solta passaria por acidente: ela já existe
    # neste mesmo corpo nas chamadas a `_manual_operation_blocks`. A asserção
    # tem de olhar a chamada certa.
    assert re.search(r"_transient_backoff\([^)]*command_mode", corpo), (
        "o backoff temporário voltou a ser escolhido só por fast_mode"
    )
    # CONTROLE: o limite é aplicado só em modo comando; fora dele a telemetria
    # de fundo tem de conservar o backoff longo, que é o que protege a conta.
    assert corpo.count("if command_mode:") >= 3


# ---------------------------------------------------------------------------
# 3. Um comando físico, uma espera só.
# ---------------------------------------------------------------------------


def test_identified_boost_adopts_the_anonymous_wait_instead_of_twinning() -> None:
    """O caso de campo: a gêmea sem id que confirma sozinha."""
    with Harness() as h:
        sid = h.subscribe()

        # Quem armou primeiro não conhecia o id (site antigo, ou o arme interno
        # antes de o id viajar).
        anonima = h.command(sid, "trunk_close", None)
        assert anonima["pending_confirmations"] == 1
        assert str(h.pending(sid)[0]["request_id"] or "") == ""

        # Agora o id chega, para o MESMO comando físico.
        batizada = h.command(sid, "trunk_close", "req-portamalas")
        assert batizada["confirmation_window_reused"] is True, (
            "o boost com id criou uma segunda espera para o mesmo comando"
        )
        assert batizada["pending_confirmations"] == 1

        pendentes = h.pending(sid)
        assert len(pendentes) == 1, f"{len(pendentes)} esperas para um comando só"
        assert str(pendentes[0]["request_id"]) == "req-portamalas", (
            "a espera continuou anônima e a próxima repetição criaria a gêmea de novo"
        )

        # CONTROLE NEGATIVO: id DIFERENTE continua sendo outro comando. Sem
        # isto, o conserto viraria "toda repetição adota a primeira espera" e a
        # 1.12.62 seria desfeita.
        outro = h.command(sid, "trunk_close", "req-outro")
        assert outro["confirmation_window_reused"] is False
        assert len(h.pending(sid)) == 2


def test_anonymous_boost_still_adopts_an_identified_wait() -> None:
    """O caminho que a 1.12.62 comprou não pode regredir."""
    with Harness() as h:
        sid = h.subscribe()
        h.command(sid, "sunshade_open", "req-cortina")
        adotado = h.command(sid, "sunshade_open", None)
        assert adotado["confirmation_window_reused"] is True
        assert len(h.pending(sid)) == 1
        assert str(h.pending(sid)[0]["request_id"]) == "req-cortina", (
            "o boost sem id apagou a identidade da espera"
        )


def test_resolved_command_is_never_resurrected_from_the_legacy_columns() -> None:
    """A entrada fantasma nasce aqui: colunas que sobrevivem ao veredito.

    O contexto guardado na assinatura NÃO traz o `request_id` — é assim que a
    entrada ressuscitada aparece no log "sem request_id", exatamente como foi
    observada às 13:43:23 e às 14:03:43. Com id igual ao da linha já resolvida o
    `INSERT OR IGNORE` bateria na chave primária e não haveria fantasma nenhum;
    é a AUSÊNCIA do id que dá a ela um `confirmation_id` próprio.
    """
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine

        despachado_em = time.time() - 40
        with engine.lock, engine._db() as db:
            # Estado de campo: o comando foi despachado, confirmado, e as
            # colunas da assinatura continuaram preenchidas porque OUTRA espera
            # ainda estava pendente no ciclo que as leu.
            db.execute(
                "UPDATE subscriptions SET command_until=?, command_key=?, command_vehicle_id=?, "
                "command_context_json=?, command_poll_count=?, command_started_at=? WHERE subscription_id=?",
                (
                    time.time() + 120,
                    "sunshade_close",
                    "V1",
                    "{}",
                    3,
                    despachado_em,
                    sid,
                ),
            )
            db.execute(
                "INSERT INTO command_confirmations "
                "(confirmation_id,subscription_id,request_id,command_key,command_vehicle_id,context_json,"
                "started_at,expires_at,poll_count,evaluated_samples,stale_samples,status,resolution,resolved_at,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,'confirmed','telemetry_match',?,?,?)",
                (
                    f"{sid}|req-cortina",
                    sid,
                    "req-cortina",
                    "sunshade_close",
                    "V1",
                    json.dumps({"request_id": "req-cortina"}),
                    despachado_em,
                    despachado_em + 180,
                    3,
                    despachado_em + 20,
                    "2026-08-02T14:03:08Z",
                    "2026-08-02T14:03:08Z",
                ),
            )
            subscription = db.execute(
                "SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)
            ).fetchone()
            engine._adopt_legacy_confirmation(db, subscription, time.time())

        assert h.pending(sid) == [], (
            "um comando já confirmado voltou como espera nova; é ela que confirma "
            "na primeira leitura e rouba a leitura do comando seguinte"
        )


def test_a_genuinely_inflight_command_is_still_adopted() -> None:
    """CONTROLE: a guarda não pode engolir a adoção que a 1.12.62 comprou."""
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine
        despachado_em = time.time() - 30
        with engine.lock, engine._db() as db:
            db.execute(
                "UPDATE subscriptions SET command_until=?, command_key=?, command_vehicle_id=?, "
                "command_context_json=?, command_poll_count=?, command_started_at=? WHERE subscription_id=?",
                (
                    time.time() + 120,
                    "trunk_open",
                    "V1",
                    json.dumps({"request_id": "req-antigo"}),
                    2,
                    despachado_em,
                    sid,
                ),
            )
            subscription = db.execute(
                "SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)
            ).fetchone()
            engine._adopt_legacy_confirmation(db, subscription, time.time())

        pendentes = h.pending(sid)
        assert len(pendentes) == 1
        assert str(pendentes[0]["command_key"]) == "trunk_open"
        assert int(pendentes[0]["poll_count"]) == 2

    # E um veredito ANTERIOR ao despacho atual não bloqueia a adoção: o dono
    # pode abrir o porta-malas de novo cinco minutos depois.
    with Harness() as h:
        sid = h.subscribe()
        engine = h.engine
        antigo = time.time() - 600
        agora_despachado = time.time() - 10
        with engine.lock, engine._db() as db:
            db.execute(
                "INSERT INTO command_confirmations "
                "(confirmation_id,subscription_id,request_id,command_key,command_vehicle_id,context_json,"
                "started_at,expires_at,poll_count,evaluated_samples,stale_samples,status,resolution,resolved_at,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,1,0,0,'confirmed','telemetry_match',?,?,?)",
                (
                    f"{sid}|req-velho",
                    sid,
                    "req-velho",
                    "trunk_open",
                    "V1",
                    "{}",
                    antigo,
                    antigo + 180,
                    antigo + 30,
                    "2026-08-02T13:50:00Z",
                    "2026-08-02T13:50:00Z",
                ),
            )
            db.execute(
                "UPDATE subscriptions SET command_until=?, command_key=?, command_vehicle_id=?, "
                "command_context_json=?, command_poll_count=0, command_started_at=? WHERE subscription_id=?",
                (
                    time.time() + 120,
                    "trunk_open",
                    "V1",
                    json.dumps({"request_id": "req-novo"}),
                    agora_despachado,
                    sid,
                ),
            )
            subscription = db.execute(
                "SELECT * FROM subscriptions WHERE subscription_id=?", (sid,)
            ).fetchone()
            engine._adopt_legacy_confirmation(db, subscription, time.time())

        assert len(h.pending(sid)) == 1, (
            "um veredito antigo do mesmo comando bloqueou a adoção do despacho novo"
        )


# ---------------------------------------------------------------------------
# 4. O cliente compartilhado serve ao consumidor mais exigente.
# ---------------------------------------------------------------------------


def test_dispatch_borrows_a_longer_timeout_and_gives_it_back() -> None:
    """O despacho ganha os segundos; a telemetria não paga por eles.

    1.12.71 — a 1.12.70 elevava o tempo limite do CLIENTE, e o mesmo cliente faz
    a leitura de telemetria, que segura a trava da conta durante a chamada.
    Alongar a leitura alonga a espera de quem manda o comando seguinte (a causa 4
    dos logs de 02/08/2026: 36s esperando uma trava do poller). A biblioteca lê
    `self.timeout` na hora da chamada, então o empréstimo é possível.
    """
    with Harness() as h:
        engine = h.engine
        piso = telemetry.TelemetryEngine.COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS

        # 12,686s medidos no despacho mais lento observado (`sunshade_position`,
        # 02/08/2026). O piso tem de dar folga real, não empatar.
        assert piso >= 20, f"o piso de {piso}s deixa o despacho medido a menos de 8s do limite"
        # E não pode passar do teto que o create_client aceita.
        assert piso <= 45

        class Cliente:
            def __init__(self, timeout: int) -> None:
                self.timeout = timeout

        # Configurado abaixo do piso: o despacho recebe o piso e devolve o valor
        # da telemetria, inclusive quando o despacho levanta.
        cliente = Cliente(15)
        with engine._dispatch_timeout(cliente):
            durante = cliente.timeout
        assert durante == piso, f"o despacho correu com {durante}s, não com o piso de {piso}s"
        assert cliente.timeout == 15, "o tempo limite da telemetria não foi devolvido"

        cliente = Cliente(15)
        try:
            with engine._dispatch_timeout(cliente):
                raise RuntimeError("a nuvem recusou")
        except RuntimeError:
            pass
        assert cliente.timeout == 15, (
            "despacho que levanta deixou o cliente alongado, e a leitura seguinte "
            "seguraria a trava da conta por mais tempo"
        )

        # Quem configurou MAIS continua com o que configurou: é piso, não valor.
        cliente = Cliente(30)
        with engine._dispatch_timeout(cliente):
            assert cliente.timeout == 30
        assert cliente.timeout == 30

        # Biblioteca sem o atributo não quebra o despacho.
        class SemTimeout:
            pass

        mudo = SemTimeout()
        with engine._dispatch_timeout(mudo):
            pass
        assert not hasattr(mudo, "timeout")

    fonte = (APP / "telemetry_engine.py").read_text(encoding="utf-8")
    criacao = fonte[fonte.index("def _create_persistent_session_locked"):]
    criacao = criacao[: criacao.index("client.login()")]
    assert "COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS" not in criacao, (
        "o piso voltou a ser gravado no cliente; a leitura de telemetria passa a "
        "segurar a trava da conta por mais tempo"
    )
    despacho = fonte[fonte.index("def execute_command"):]
    despacho = despacho[: despacho.index("def _dispatch_timeout")]
    assert "_dispatch_timeout(" in despacho, (
        "o despacho voltou a correr com o tempo limite da telemetria"
    )


def test_the_library_has_no_wake_primitive_and_the_code_says_so() -> None:
    """O que impede a próxima sessão de reimplementar algo inerte.

    A decisão registrada em 02/08/2026 era "forçar refresh/wakeUp antes de
    amostrar". Medido contra a leapmotor-api fixada em requirements.txt: não
    existe primitiva de despertar. Este contrato falha se alguém remover o
    registro dessa medição — ou, melhor, se a biblioteca ganhar a primitiva,
    porque aí a decisão volta a ser implementável.
    """
    connector = sys.modules["leaphub_connector"]
    fonte = (APP / "connector.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("def try_wake_vehicle"):]
    corpo = corpo[: corpo.index("def resolve_command_vehicle")]

    nomes = [
        nome
        for nome in ("wake_vehicle", "wake_up_vehicle", "wakeup_vehicle", "wake_vehicle_up", "wake_up", "wakeup")
        if f'"{nome}"' in corpo
    ]
    assert len(nomes) >= 6, "a busca por reflexão perdeu nomes de método"

    class SemDespertar:
        """O cliente real da 0.3.2: leitura de estado e comandos, e nada mais."""

        def get_vehicle_status(self, vehicle): ...
        def open_trunk(self, vin): ...

    assert connector.try_wake_vehicle(SemDespertar(), "VIN") == {"attempted": False, "method": None}

    # E a medição fica escrita onde quem for reimplementar vai ler.
    assert "0.3.2" in corpo and "inerte" in corpo, (
        "o registro da medição saiu do código; a decisão de 02/08 seria "
        "reimplementada como código que não faz nada"
    )
