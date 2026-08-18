#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import http.client
import hmac
import json
import logging
import os
import random
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from cryptography.fernet import Fernet, InvalidToken

import leaphub_connector as connector
try:
    from leaphub_connection_orchestrator import ORCHESTRATOR
except ModuleNotFoundError:
    try:
        from connection_orchestrator import ORCHESTRATOR
    except ModuleNotFoundError:
        import importlib.util as _importlib_util
        _orchestrator_path = Path(__file__).with_name("connection_orchestrator.py")
        _orchestrator_spec = _importlib_util.spec_from_file_location("leaphub_connection_orchestrator_local", _orchestrator_path)
        if _orchestrator_spec is None or _orchestrator_spec.loader is None:
            raise
        _orchestrator_module = _importlib_util.module_from_spec(_orchestrator_spec)
        _orchestrator_spec.loader.exec_module(_orchestrator_module)
        ORCHESTRATOR = _orchestrator_module.ORCHESTRATOR
try:
    from leaphub_event_transport import EVENT_TRANSPORT
except ModuleNotFoundError:
    try:
        from event_transport import EVENT_TRANSPORT
    except ModuleNotFoundError:
        import importlib.util as _event_importlib_util
        _event_transport_path = Path(__file__).with_name("event_transport.py")
        _event_transport_spec = _event_importlib_util.spec_from_file_location("leaphub_event_transport_local", _event_transport_path)
        if _event_transport_spec is None or _event_transport_spec.loader is None:
            raise
        _event_transport_module = _event_importlib_util.module_from_spec(_event_transport_spec)
        _event_transport_spec.loader.exec_module(_event_transport_module)
        EVENT_TRANSPORT = _event_transport_module.EVENT_TRANSPORT

LOG = logging.getLogger("leaphub.telemetry")
ENGINE_VERSION = "1.12.111"  # windows C10 mapping + final confirmation push; retry/cadence preserved

# Hospedagem compartilhada (Apache/LiteSpeed) fecha a conexão ociosa em poucos
# segundos. Reaproveitar depois disso escreve num socket já fechado e devolve
# "Remote end closed connection without response" sem que o PHP chegue a rodar.
DELIVERY_IDLE_DEFAULT_SECONDS = 5.0
DELIVERY_IDLE_MIN_SECONDS = 2.0
DELIVERY_IDLE_MAX_SECONDS = 30.0

# 1.12.91 — o precheck do comando lê apenas a assinatura local. Essa leitura
# não pode depender de `self.lock`: em campo um quick_heat ficou 12.292s só
# esperando a trava GLOBAL, apesar de `latência_conta=1ms` e `dispatch=612ms`;
# em duas tentativas anteriores o mesmo gargalo atingiu o teto de 20s e o
# comando nem chegou ao veículo. SQLite/WAL já dá snapshot consistente para
# SELECT; em fallback sem WAL, a própria leitura recebe um teto curto.
COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS = 0.75

# 1.12.82 — uma leitura AUTOMÁTICA nunca pode manter a trava da conta por
# dezenas de segundos enquanto o dono tenta enviar um comando. O cliente
# persistente continua com o timeout configurado; somente chamadas feitas pela
# telemetria emprestam este teto curto. O despacho manual continua usando
# `_dispatch_timeout`, portanto esta proteção não encurta o comando do usuário.
TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0

# 1.12.92 — diagnóstico somente. Não altera timeout, polling nem quantidade de
# chamadas. Etapas que segurarem a conta por tempo perceptível ganham uma linha
# própria para que o próximo ajuste seja feito sobre a causa medida, não por
# aproximação.
TELEMETRY_STAGE_LOG_THRESHOLD_MS = 750

# 1.12.111 — manutencao local e BEST EFFORT. Em campo a primeira limpeza da
# 1.12.110 monopolizou o escritor SQLite por 39-42s; boost recebeu 503 e
# a confirmacao FAST acumulou >32s de atraso. Estes tetos nao alteram
# polling do carro, payload fisico, auth ou fila de entrega.
MAINTENANCE_STARTUP_GRACE_SECONDS = 180.0
MAINTENANCE_INTERVAL_SECONDS = 60.0
MAINTENANCE_BUSY_TIMEOUT_SECONDS = 0.15
MAINTENANCE_BATCH_SIZE = 200
MAINTENANCE_WORKER_POLL_SECONDS = 30.0

# 1.12.78 — o anúncio do fim do comando é melhor esforço, e o teto é curto de
# propósito. Ele existe para o site não esperar a próxima volta do cron; se
# demorar mais que isso, o ciclo do cron reconcilia do mesmo jeito e insistir só
# gastaria a conexão residencial. O destino é derivado da URL de telemetria já
# configurada, trocando somente o sufixo da rota — nenhuma opção nova precisa
# ser preenchida na instalação de campo.
COMMAND_ANNOUNCE_TIMEOUT_SECONDS = 8.0
COMMAND_ANNOUNCE_SOURCE_SUFFIX = "/api/internal/telemetry/events"
COMMAND_ANNOUNCE_TARGET_SUFFIX = "/api/internal/commands/result"

TELEMETRY_CONFIRMABLE_COMMANDS = frozenset({
    "lock",
    "unlock",
    "climate_on",
    "climate_off",
    "quick_cool",
    "quick_heat",
    "windshield_defrost",
    "prepare_car",
    "battery_preheat_on",
    "battery_preheat_off",
    "steering_wheel_heat_on",
    "steering_wheel_heat_off",
    "rearview_mirror_heat_on",
    "rearview_mirror_heat_off",
    "trunk_open",
    "trunk_close",
    "sunshade_open",
    "sunshade_close",
    "sunshade_position",
    "windows_open",
    "windows_close",
    "windows_position",
    "sentry_on",
    "sentry_off",
    "start_charging",
    "stop_charging",
    "set_charge_limit",
})

# 1.12.84 — uma ação de estado mais nova torna semanticamente obsoleta a
# espera oposta anterior. A telemetria não deve continuar por 180s tentando
# confirmar LOCK depois de um UNLOCK posterior, nem OPEN depois de CLOSE.
CONFIRMATION_SUPERSESSION_FAMILIES: dict[str, frozenset[str]] = {
    "locks": frozenset({"lock", "unlock"}),
    "climate": frozenset({"climate_on", "climate_off", "quick_cool", "quick_heat", "windshield_defrost", "prepare_car"}),
    "trunk": frozenset({"trunk_open", "trunk_close"}),
    "windows": frozenset({"windows_open", "windows_close", "windows_position"}),
    "sunshade": frozenset({"sunshade_open", "sunshade_close", "sunshade_position"}),
    "charging": frozenset({"start_charging", "stop_charging"}),
    "battery_preheat": frozenset({"battery_preheat_on", "battery_preheat_off"}),
    "steering_heat": frozenset({"steering_wheel_heat_on", "steering_wheel_heat_off"}),
    "mirror_heat": frozenset({"rearview_mirror_heat_on", "rearview_mirror_heat_off"}),
}
CONFIRMATION_SUPERSESSION_GROUP = {
    command: family
    for family, commands in CONFIRMATION_SUPERSESSION_FAMILIES.items()
    for command in commands
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log_slow_telemetry_stage(subscription_id: str, stage: str, started_at: float, *, origin: str = "telemetry") -> int:
    """Log only slow local/cloud stages; never changes control flow or retries."""
    elapsed_ms = int(round((time.monotonic() - started_at) * 1000))
    if elapsed_ms >= TELEMETRY_STAGE_LOG_THRESHOLD_MS:
        LOG.info(
            "Telemetria %s etapa=%s demorou=%sms origem=%s.",
            str(subscription_id or "")[:96],
            str(stage or "unknown")[:64],
            elapsed_ms,
            str(origin or "telemetry")[:40],
        )
    return elapsed_ms


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=connector.json_default).encode("utf-8")


VOLATILE_SEMANTIC_KEYS = {
    "captured_at",
    "collect_time",
    "create_time",
    "synced_at",
    "sent_at",
    "gateway_collected_at",
    "visual_sample_fingerprint",
    "sample_fingerprint",
    "data_base64",
}


def semantic_snapshot(value: Any, parent_key: str = "") -> Any:
    """Remove transport timestamps while preserving every actual vehicle state."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key in VOLATILE_SEMANTIC_KEYS:
                continue
            if parent_key == "maintenance" and key == "synced_at":
                continue
            result[key] = semantic_snapshot(item, key)
        return result
    if isinstance(value, list):
        return [semantic_snapshot(item, parent_key) for item in value]
    return value


class _SQLiteWriterConnection:
    """Proxy reutilizavel por thread: SELECTs WAL livres; writers serializados."""

    _WRITE_HEADS = frozenset({
        "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP",
        "VACUUM", "REINDEX", "ANALYZE",
    })
    _TX_BEGIN = frozenset({"BEGIN", "SAVEPOINT"})
    _TX_END = frozenset({"COMMIT", "ROLLBACK", "END"})

    def __init__(self, db: sqlite3.Connection, writer_lock: threading.RLock) -> None:
        self._db = db
        self._writer_lock = writer_lock
        self._writer_held = False
        self._context_depth = 0

    def matches(self, db: sqlite3.Connection) -> bool:
        return self._db is db

    def enter_context(self) -> None:
        self._context_depth += 1

    def leave_context(self) -> None:
        if self._context_depth > 0:
            self._context_depth -= 1
        if self._context_depth == 0:
            self.release_writer_guard()

    @staticmethod
    def _head(sql: str) -> str:
        text = str(sql or "").lstrip()
        while text.startswith("--"):
            _line, _sep, text = text.partition("\n")
            text = text.lstrip()
        if text.startswith("/*"):
            end = text.find("*/")
            if end >= 0:
                text = text[end + 2:].lstrip()
        return text.split(None, 1)[0].upper() if text else ""

    @classmethod
    def _is_write(cls, sql: str) -> bool:
        head = cls._head(sql)
        if head in cls._WRITE_HEADS:
            return True
        if head == "PRAGMA":
            text = str(sql or "")
            return "=" in text or "(" in text
        if head == "WITH":
            upper = " " + str(sql or "").upper().replace("\n", " ") + " "
            return any(f" {token} " in upper for token in ("INSERT", "UPDATE", "DELETE", "REPLACE"))
        return False

    def _begin_writer(self) -> None:
        if not self._writer_held:
            self._writer_lock.acquire()
            self._writer_held = True

    def _end_writer(self) -> None:
        if self._writer_held:
            self._writer_held = False
            self._writer_lock.release()

    def execute(self, sql: str, parameters: object = ()):
        head = self._head(sql)
        if head in self._TX_BEGIN:
            self._begin_writer()
            try:
                return self._db.execute(sql, parameters)
            except BaseException:
                self._end_writer()
                raise
        if head in self._TX_END:
            try:
                return self._db.execute(sql, parameters)
            finally:
                self._end_writer()
        if head == "RELEASE":
            try:
                result = self._db.execute(sql, parameters)
            finally:
                if not self._db.in_transaction:
                    self._end_writer()
            return result
        if self._is_write(sql):
            if self._writer_held:
                return self._db.execute(sql, parameters)
            with self._writer_lock:
                return self._db.execute(sql, parameters)
        return self._db.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: object):
        if self._is_write(sql):
            if self._writer_held:
                return self._db.executemany(sql, seq_of_parameters)
            with self._writer_lock:
                return self._db.executemany(sql, seq_of_parameters)
        return self._db.executemany(sql, seq_of_parameters)

    def executescript(self, sql_script: str):
        if self._writer_held:
            try:
                return self._db.executescript(sql_script)
            finally:
                if not self._db.in_transaction:
                    self._end_writer()
        with self._writer_lock:
            return self._db.executescript(sql_script)

    def commit(self) -> None:
        try:
            self._db.commit()
        finally:
            self._end_writer()

    def rollback(self) -> None:
        try:
            self._db.rollback()
        finally:
            self._end_writer()

    def abort_writer_transaction(self) -> None:
        if not self._writer_held:
            return
        try:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        finally:
            self._end_writer()

    def release_writer_guard(self) -> None:
        self.abort_writer_transaction()

    def __getattr__(self, name: str):
        return getattr(self._db, name)


class TelemetryYieldForManual(RuntimeError):
    """A coleta automática cedeu a conta para uma operação manual."""


class TelemetryEngine:
    """Adaptive polling and encrypted persistent delivery queue."""

    # 1.12.62 — piso e teto do orçamento de leituras da janela de confirmação.
    # Ficam aqui para que o `gateway_manager` e os contratos leiam o número de
    # uma fonte só: quando o piso subiu de 5 para 8, o valor estava repetido em
    # três lugares e um contrato reprovava por carimbar o antigo.
    COMMAND_MAX_POLLS_FLOOR = 8
    COMMAND_MAX_POLLS_CEILING = 64

    # 1.12.75 — espelha o teto de `seconds` em `signal_presence`
    # (`max(30, min(180, int(seconds)))`). O piso do orçamento é DERIVADO dele;
    # ver o comentário em `__init__`.
    COMMAND_WINDOW_CEILING_SECONDS = 180

    # 1.12.70 — backoff próprio da janela de confirmação.
    #
    # A falha temporária escolhia o backoff por `fast_mode`, que é
    # `interactive or command_mode`: presença na tela e espera de comando
    # entravam no mesmo balde. Um `Read timed out` durante a confirmação
    # mandava a próxima leitura para 45s (site aberto) ou 120s (site fechado),
    # dentro de uma janela que dura 180s e cuja cadência começa em 12s. Uma
    # única falha consumia a janela inteira.
    #
    # Medido em campo em 02/08/2026: `trunk_close` despachado às 14:03:36 e
    # aceito pela nuvem às 14:03:38; `Read timed out` às 14:04:10 com "nova
    # leitura em 45s"; o comando nunca apareceu confirmado.
    COMMAND_TRANSIENT_BACKOFF = (8, 15, 25, 40, 60, 90)

    # Folga mínima entre a leitura reagendada e o fim da janela. Uma leitura que
    # chega depois do prazo não confirma nada: `_evaluate_confirmation` encerra
    # a espera por `window_deadline` antes de olhar a amostra.
    COMMAND_WINDOW_MIN_MARGIN_SECONDS = 3

    # 1.12.70 — o cliente Leapmotor da sessão persistente é o mesmo que despacha
    # os comandos, e o despacho é bem mais lento que a leitura de status. Com o
    # padrão de 15s da telemetria, `sunshade_position` (12,686s medidos em
    # 02/08/2026) passava a 2,3s do limite. O piso vale para instalações
    # existentes, que guardam o valor antigo em `telemetry_request_timeout_seconds`
    # e nunca releriam um novo padrão do config.yaml.
    #
    # 1.12.71 — e é emprestado SÓ ao despacho (`_dispatch_timeout`), não gravado
    # no cliente. Quem segura a trava da conta durante a chamada é a leitura de
    # telemetria; alongá-la alonga a espera do comando seguinte.
    COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS = 25

    # 1.12.74 — teto da PRIMEIRA releitura depois do comando, e o motivo é o
    # carro, não a nuvem: ele retranca sozinho em ~30s. Com a cadência antiga
    # (12s para a primeira, +20s para a segunda) a confirmação do `unlock` de
    # 11/08/2026 saiu às 13:11:45 para um comando despachado às 13:10:47 — 54s,
    # cinco leituras — e chegou na tela dizendo "destravado" quando o carro já
    # tinha retrancado. Segundos depois a leitura seguinte, essa fresca, dizia
    # "travado". A tela nunca esteve errada; estava atrasada.
    #
    # É TETO em código, e não padrão no config.yaml, porque a instalação
    # existente guarda o valor antigo da opção e nunca releria um padrão novo —
    # a mesma razão de COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS e de
    # COMMAND_MAX_POLLS_FLOOR.
    #
    # 1.12.77 — a frase que ficava aqui ("o orçamento total de leituras não
    # muda: são as mesmas 8, apenas distribuídas mais cedo") não descrevia a
    # 1.12.74: ela ERA o defeito dela. Manter a CONTAGEM enquanto se adensa a
    # escada transformou o teto de segurança no critério de encerramento. O piso
    # do orçamento passou a ser DERIVADO em `__init__` na 1.12.75 — ver
    # COMMAND_WINDOW_CEILING_SECONDS —, mas o comentário ficou para trás,
    # contradizendo o código logo abaixo dele.
    COMMAND_FIRST_POLL_CEILING_SECONDS = 6
    COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)  # 1.12.96: somente janela pós-despacho

    # 1.12.77 — teto da cadência com a tela aberta.
    #
    # `interactive_seconds` valia 20s (piso 15s) e governa TODOS os estados
    # quando há presença: ver o ramo `if interactive:` de `_adaptive_interval`.
    # Medido em campo em 12/08/2026, o carro publica uma mudança de trava em
    # ~0-12s (`lock` confirmou em 0s, 1s e 12s). Com leitura a cada 20s, boa
    # parte da espera que o dono sente é NOSSA, não do carro.
    #
    # A cortina NÃO serve para calibrar isto: ela leva 30-40s no próprio
    # mecanismo, confirmado pelo dono. Foi confundindo tempo de mecanismo com
    # latência de telemetria que este número atravessou tanto tempo sem ser
    # questionado — inclusive por mim, nesta mesma sessão.
    #
    # 6s não é número novo: é o primeiro degrau da escada de confirmação de
    # comando (COMMAND_FIRST_POLL_CEILING_SECONDS), que já roda em produção sem
    # disparar rate-limit. Adotar um valor JÁ PROVADO evita trocar 20s de atraso
    # por 900s de cooldown — o castigo é 45x maior que o problema.
    #
    # TETO em código pelo mesmo motivo dos vizinhos: a instalação existente tem
    # `telemetry_interactive_seconds: 20` gravado e nunca releria um padrão novo.
    INTERACTIVE_SECONDS_CEILING = 6

    def __init__(
        self,
        options: dict[str, Any],
        secrets: dict[str, str],
        operation_semaphore: threading.BoundedSemaphore,
        account_lock_provider: Callable[[str, dict[str, Any]], Any] | None = None,
        account_wait_seconds: int = 20,
        manual_pending_provider: Callable[[str, dict[str, Any]], bool] | None = None,
        manual_active_provider: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self.options = options
        self.secrets = secrets
        self.operation_semaphore = operation_semaphore
        self.account_lock_provider = account_lock_provider
        self.account_wait_seconds = max(2, min(60, int(account_wait_seconds)))
        self.manual_pending_provider = manual_pending_provider
        # A confirmação de um comando pode ignorar apenas a janela de "settle"
        # deixada para uma possível ação seguinte. Um comando realmente pendente
        # continua tendo prioridade e faz a coleta ceder no próximo ponto seguro.
        self.manual_active_provider = manual_active_provider or manual_pending_provider
        self.data_dir = Path(os.getenv("LEAPHUB_TELEMETRY_DIR", "/data/telemetry"))
        self.db_path = self.data_dir / "telemetry.sqlite"
        self.key_path = self.data_dir / "telemetry.key"
        self.migration_marker_path = self.data_dir / ".journal-migration.lock"
        self.instance_lock_path = self.data_dir / ".engine.lock"
        self._instance_lock_handle = None
        self.storage_lock = threading.RLock()
        self.storage_healthy = False
        self.storage_failures = 0
        self.storage_last_error = ""
        self.storage_last_error_at = ""
        self.storage_next_retry_at = 0.0
        self.storage_next_log_at = 0.0
        self.storage_journal_mode = "unknown"
        self._prepare_storage(probe=True)
        self._acquire_instance_lock()
        self.fernet = Fernet(self._load_key())
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.lock = threading.RLock()
        # 1.12.110 — agenda/confirmacao nao divide a trava global com fila, entrega,
        # auth ou manutencao. SQLite continua sendo a autoridade transacional.
        self.schedule_lock = threading.RLock()
        # 1.12.111-R6 — apenas writers do telemetry.sqlite passam aqui;
        # SELECTs continuam concorrentes em WAL. Nunca envolver rede.
        self.sqlite_writer_lock = threading.RLock()
        self._connections: dict[int, sqlite3.Connection] = {}
        # 1.12.111-R6 — o proxy de cada conexao tambem e reutilizado por thread;
        # preserva o contrato de identidade da 1.12.50/51 sem abrir writer paralelo.
        self._writer_connections: dict[int, _SQLiteWriterConnection] = {}
        self._busy_ms: dict[int, int] = {}
        self._connections_guard = threading.RLock()
        self._storage_checked_at = 0.0
        self._maintenance_last_at = 0.0
        # 1.12.50 — a coleta de uma conta não atrasa mais a das outras. O teto
        # real de chamadas simultâneas à nuvem continua sendo o semáforo global
        # do Connector; isto apenas deixa de serializar tudo antes dele.
        self.poll_workers = self._bounded("telemetry_poll_workers", 3, 1, 6)
        self._poll_pool: ThreadPoolExecutor | None = None
        # 1.12.93 — o envio físico não espera mais o bookkeeping SQLite da
        # confirmação. Um ÚNICO worker FIFO mantém a ordem das intenções
        # (abrir->fechar, lock->unlock) sem tocar no cliente Leapmotor.
        self._confirmation_arm_pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="leaphub-confirm-arm",
        )
        # 1.12.94 — imagem tem fila própria e recebe somente snapshot JSON.
        # Nunca recebe cliente/token/credenciais e nunca usa account_lock,
        # operation_semaphore ou _session_operation_lock.
        # 1.12.95 — dois workers LOCAIS impedem uma conta de esperar a fila
        # visual de outra. Nenhum deles recebe cliente Leapmotor ou trava da conta.
        self.visual_render_workers = 2
        self._visual_render_pool: ThreadPoolExecutor | None = ThreadPoolExecutor(
            max_workers=self.visual_render_workers,
            thread_name_prefix="leaphub-visual",
        )
        self._visual_render_guard = threading.RLock()
        self._visual_render_generation: dict[str, int] = {}
        self._visual_render_signature: dict[str, str] = {}
        self._visual_jobs_pending = 0
        self._inflight: set[str] = set()
        self._inflight_guard = threading.RLock()
        self.delivery_event = threading.Event()
        self.delivery_worker: threading.Thread | None = None
        self.maintenance_worker: threading.Thread | None = None
        # 1.12.51 — conexao TLS reaproveitada entre lotes de entrega.
        self._delivery_connection: http.client.HTTPConnection | None = None
        self._delivery_connection_key = ""
        self._delivery_guard = threading.RLock()
        # 1.12.52 — a conexao so pode ser reaproveitada dentro da janela de
        # keep-alive do servidor. Os lotes saem a cada 20-120s e a hospedagem
        # fecha a conexao ociosa muito antes disso.
        self._delivery_connection_idle_since = 0.0
        self._delivery_idle_max = DELIVERY_IDLE_DEFAULT_SECONDS
        self.active_seconds = self._bounded("telemetry_active_seconds", 20, 15, 300)
        # 1.12.77 — o valor gravado na instalação é puxado para BAIXO pelo teto
        # em código; sem o `min`, a instalação de campo seguiria em 20s. O piso
        # de 5s não é estética: o round-trip HTTPS medido em 12/08/2026 ficou
        # entre 2,1s e 4,5s, e um intervalo abaixo disso empilha chamada sobre
        # chamada sem trazer dado novo — o `status/get` devolve o último
        # snapshot que o CARRO subiu, não uma leitura ao vivo.
        self.interactive_seconds = min(
            self._bounded("telemetry_interactive_seconds", self.INTERACTIVE_SECONDS_CEILING, 5, 60),
            self.INTERACTIVE_SECONDS_CEILING,
        )
        # Janela curta após comandos remotos. É propositalmente separada da
        # navegação comum para confirmar rapidamente o novo estado sem manter
        # consultas agressivas à nuvem durante todo o dia.
        # A confirmação após comando usa poucas leituras espaçadas. O app
        # mantém o último estado confirmado enquanto aguarda, portanto não há
        # motivo para consultar a nuvem a cada três segundos.
        self.command_seconds = self._bounded("telemetry_command_seconds", 12, 10, 60)
        # 1.12.62 — este número deixou de ser o critério de encerramento e passou
        # a ser teto de segurança: quem fecha a espera é o prazo da janela
        # (`command_until`, até 180s). Com cinco leituras a cadência abaixo
        # esgotava a janela em ~112s, e um carro que acabara de acordar era
        # declarado inconclusivo com quase um minuto ainda disponível — foi o que
        # aconteceu em campo com o `unlock` cuja amostra chegou a +89s. O piso
        # cobre os 180s inteiros com a cadência abaixo; instalações com o valor
        # legado menor são elevadas a ele automaticamente.
        #
        # 1.12.75 — e na 1.12.74 eu o quebrei. Adensei a escada e mantive "as
        # mesmas 8 leituras": a 8ª saiu de 382s para 195s, e o TETO passou a
        # encerrar a espera antes do PRAZO. Medido em campo em 11/08/2026: duas
        # janelas de `unlock` fechadas por "orçamento de leituras esgotado" aos
        # 135s e aos 60s, com 180s disponíveis nas duas.
        #
        # Basta UMA leitura extra para isso, e ela é comum: a cadência acompanha
        # a espera mais nova (`min(poll_count)`) enquanto cada leitura consome o
        # orçamento de TODAS as pendentes. Apertar um segundo botão reinicia a
        # escada no primeiro degrau e queima o resto do orçamento do comando
        # anterior em segundos — foi o que aconteceu às 14:52:55.
        #
        # O piso agora é DERIVADO, não escolhido: é quantas leituras cabem na
        # janela cheia com o menor degrau da escada. Elevá-lo não cria requisição
        # nenhuma — quem marca o ritmo é a cadência; o teto só trunca.
        first_step = max(1, min(self.command_seconds, self.COMMAND_POST_DISPATCH_EARLY_CADENCE[0]))
        derived_floor = -(-self.COMMAND_WINDOW_CEILING_SECONDS // first_step) + 1
        polls_floor = max(self.COMMAND_MAX_POLLS_FLOOR, derived_floor)
        self.command_max_polls = self._bounded(
            "telemetry_command_max_polls",
            polls_floor,
            polls_floor,
            max(self.COMMAND_MAX_POLLS_CEILING, polls_floor),
        )
        # 1.12.74 — a escada antiga era (12, 20, 35, 45, 60, 90, 120, 120):
        # acumulada 0, 12, 32, 67, 112, 172, 262, 382, com apenas três leituras
        # dentro dos primeiros 32s e os dois últimos degraus fora da janela de
        # 180s, onde `_within_command_window` tinha de encurtá-los. A nova
        # acumula 0, 6, 16, 32, 56, 90, 135, 195: quatro leituras nos primeiros
        # 32s — antes do retravamento automático do carro — e a cauda cabendo
        # na janela. Mesmo número de leituras, distribuídas onde adiantam.
        self.command_cadence = (
            min(self.command_seconds, self.COMMAND_FIRST_POLL_CEILING_SECONDS),
            10,
            16,
            24,
            34,
            45,
            60,
            90,
        )
        self.command_effective_cadence = (
            *self.COMMAND_POST_DISPATCH_EARLY_CADENCE,
            *self.command_cadence[len(self.COMMAND_POST_DISPATCH_EARLY_CADENCE):],
        )
        self.charging_seconds = self._bounded("telemetry_charging_seconds", 25, 15, 600)
        self.parked_seconds = self._bounded("telemetry_parked_seconds", 90, 60, 3600)
        self.sleep_seconds = self._bounded("telemetry_sleep_seconds", 600, 300, 14400)
        # A presença no site controla somente a cadência rápida. Quando o modo
        # de fundo está ativo, assinaturas habilitadas continuam elegíveis mesmo
        # depois de active_until expirar. O limite econômico evita ficar horas
        # sem perceber uma viagem curta, sem consultar agressivamente o carro
        # enquanto ele está parado.
        self.background_enabled = bool(options.get("telemetry_background_enabled", True))
        self.background_seconds = self._bounded("telemetry_background_seconds", 300, 120, 1800)
        self.presence_window_seconds = self._bounded("telemetry_presence_window_seconds", 420, 300, 1800)
        self.rate_limit_cooldown_seconds = self._bounded("telemetry_rate_limit_cooldown_seconds", 900, 300, 3600)
        self.login_cooldown_max_seconds = 1800
        self.login_backoff_schedule = (300, 600, 1200, 1800)
        # Evita que reinícios, várias abas ou reativações próximas iniciem novos
        # logins antes do intervalo seguro. O marcador fica no SQLite e, por
        # isso, continua válido mesmo após reiniciar o App.
        self.auth_attempt_min_interval_seconds = 150
        self.started_at = time.time()
        self.charge_watch_seconds = max(60, min(120, self.charging_seconds * 3))
        self.batch_size = self._bounded("telemetry_batch_size", 25, 1, 50)
        self.retention_days = self._bounded("telemetry_retention_days", 7, 1, 60)
        self.queue_max = self._bounded("telemetry_queue_max_events", 10000, 100, 100000)
        self.delivery_urls = {
            "staging": str(options.get("telemetry_beta_internal_url") or "").strip(),
            "production": str(options.get("telemetry_production_internal_url") or "").strip(),
        }
        self.environment_enabled = {
            "staging": bool(options.get("telemetry_beta_enabled", True)),
            "production": bool(options.get("telemetry_production_enabled", False)),
        }
        self.sessions: dict[str, dict[str, Any]] = {}
        # A tabela de sessões usa uma trava curta. Cada conta possui uma trava
        # própria para que contas diferentes possam ser consultadas em paralelo
        # sem permitir que upsert/remoção fechem uma sessão durante a leitura.
        self.session_lock = threading.RLock()
        self.session_locks_guard = threading.RLock()
        self.session_locks: dict[str, threading.RLock] = {}
        self.session_max_age_seconds = 0
        # Uma janela de telemetria encerrada não invalida o token. Preserve o
        # cliente por algumas horas e descarte somente por inatividade real,
        # credencial alterada, expiração confirmada ou desligamento do Gateway.
        self.session_idle_seconds = self._bounded("telemetry_session_idle_seconds", 21600, 1800, 86400)
        self.vehicle_list_cache_seconds = self._bounded("telemetry_vehicle_list_cache_seconds", 1800, 300, 7200)
        self.message_cache_seconds = self._bounded("telemetry_message_cache_seconds", 1800, 300, 14400)
        # 1.12.38 — o estado essencial é FAST; mensagens/imagem oficial são SLOW.
        # Não adicionamos uma opção obrigatória ao schema do add-on para manter
        # atualização compatível com instalações antigas.
        self.slow_interval_seconds = max(600, min(1800, self.message_cache_seconds))
        self.request_timeout_seconds = self._bounded("telemetry_request_timeout_seconds", 15, 10, 30)
        # Não altera a opção persistida nem o timeout de comandos. É apenas o
        # teto de uma chamada de rede enquanto a telemetria possui a conta.
        self.telemetry_network_timeout_seconds = min(
            float(self.request_timeout_seconds), TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS
        )
        self._init_db()
        self.storage_healthy = True
        # 1.12.38 — a telemetria já aceita hints de um futuro transporte por
        # eventos. O REST continua como fallback e nenhuma conexão MQTT é aberta
        # enquanto autenticação/tópicos/payloads não estiverem homologados.
        EVENT_TRANSPORT.register_wake_callback(self._wake_from_event)

    def _wake_from_event(self, environment: str, account_id: int, vehicle_id: str, source: str) -> bool:
        now = time.time()
        target_vehicle = str(vehicle_id or "").strip()[:190]
        with self.lock, self._db() as db:
            candidates = db.execute(
                "SELECT subscription_id,active_until,next_run_at,vehicle_ids_json FROM subscriptions WHERE environment=? AND account_id=? AND enabled=1 AND auth_required=0",
                (str(environment or ""), int(account_id)),
            ).fetchall()
            rows = []
            for row in candidates:
                if target_vehicle:
                    try:
                        configured = {str(item).strip() for item in json.loads(str(row["vehicle_ids_json"] or "[]"))}
                    except (TypeError, ValueError, json.JSONDecodeError):
                        configured = set()
                    if target_vehicle not in configured:
                        continue
                rows.append(row)
            for row in rows:
                active_until = max(float(row["active_until"] or 0), now + 90)
                next_run = min(float(row["next_run_at"] or now), now)
                db.execute(
                    "UPDATE subscriptions SET active_until=?, next_run_at=?, status='event_hint', updated_at=? WHERE subscription_id=?",
                    (active_until, next_run, utc_iso(), str(row["subscription_id"])),
                )
        if rows:
            LOG.debug("Hint de evento %s acordou %s assinatura(s) sem abrir chamada extra por conta própria.", str(source or "event")[:40], len(rows))
            self.wake_event.set()
            return True
        return False

    def _bounded(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.options.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _manual_operation_blocks(
        self, environment: str, operation_payload: dict[str, Any], *, command_mode: bool
    ) -> bool:
        provider = self.manual_active_provider if command_mode else self.manual_pending_provider
        return bool(provider and provider(environment, operation_payload))

    def _prepare_storage(self, probe: bool = False) -> None:
        """Garante que a fila persistente continue gravável após atualização/reinício."""
        if not probe:
            now = time.monotonic()
            if now - self._storage_checked_at < 60.0:
                return
            self._storage_checked_at = now
        with self.storage_lock:
            if self.data_dir.exists() and not self.data_dir.is_dir():
                raise OSError(f"O caminho de telemetria não é um diretório: {self.data_dir}")
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                self.data_dir.chmod(0o700)
            except OSError:
                pass
            for candidate in (
                self.db_path,
                self.key_path,
                Path(str(self.db_path) + "-wal"),
                Path(str(self.db_path) + "-shm"),
                Path(str(self.db_path) + "-journal"),
            ):
                if candidate.exists():
                    if not candidate.is_file():
                        raise OSError(f"Armazenamento inválido em {candidate}")
                    try:
                        candidate.chmod(0o600)
                    except OSError:
                        pass
            if not probe:
                return
            probe_path = self.data_dir / f".write-probe-{os.getpid()}-{threading.get_ident()}"
            descriptor = os.open(probe_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as handle:
                    handle.write(b"ok\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                try:
                    probe_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_key(self) -> bytes:
        if self.key_path.is_file():
            key = self.key_path.read_bytes().strip()
            try:
                Fernet(key)
                return key
            except (ValueError, TypeError):
                raise RuntimeError("A chave local da fila de telemetria está inválida.")
        key = Fernet.generate_key()
        descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def _acquire_instance_lock(self) -> None:
        """Impede dois Connector de abrirem a mesma fila ao mesmo tempo."""
        try:
            import fcntl
        except ImportError:
            return
        handle = self.instance_lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + 45.0
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle.seek(0)
                handle.truncate()
                handle.write(f"pid={os.getpid()} started={utc_iso()}\n")
                handle.flush()
                self._instance_lock_handle = handle
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise RuntimeError("Outra instância do Connector ainda utiliza a fila de telemetria.")
                time.sleep(0.5)

    @contextmanager
    def _journal_migration_guard(self):
        """Sinaliza ao painel que a fila está em migração e não deve ser consultada."""
        self.migration_marker_path.write_text(
            json.dumps({"pid": os.getpid(), "started_at": utc_iso()}),
            encoding="utf-8",
        )
        try:
            self.migration_marker_path.chmod(0o600)
        except OSError:
            pass
        try:
            yield
        finally:
            try:
                self.migration_marker_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _drop_connection(self, key: int) -> None:
        with self._connections_guard:
            db = self._connections.pop(key, None)
            coordinated = self._writer_connections.pop(key, None)
            self._busy_ms.pop(key, None)
        if coordinated is not None:
            # _drop_connection e chamado pela propria thread da conexao.
            coordinated.abort_writer_transaction()
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                pass

    def close_storage(self) -> None:
        """Fecha as conexoes SQLite abertas por todas as threads."""
        with self._connections_guard:
            connections = list(self._connections.values())
            self._connections.clear()
            self._writer_connections.clear()
            self._busy_ms.clear()
        # stop() encerra workers antes deste ponto; nao tentamos liberar RLock
        # pertencente a outra thread durante shutdown.
        for db in connections:
            try:
                db.close()
            except sqlite3.Error:
                pass

    def _connection(self) -> sqlite3.Connection:
        """Reaproveita uma conexão SQLite por thread em vez de reconectar por consulta."""
        key = threading.get_ident()
        with self._connections_guard:
            db = self._connections.get(key)
        if db is not None:
            try:
                db.execute("SELECT 1").fetchone()
                return db
            except sqlite3.Error:
                self._drop_connection(key)

        self._prepare_storage(probe=False)
        db = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA temp_store=MEMORY")
        # journal_mode é persistente no arquivo; synchronous é por conexão.
        mode_row = db.execute("PRAGMA journal_mode").fetchone()
        mode = str(mode_row[0] if mode_row else "").lower()
        db.execute("PRAGMA synchronous=NORMAL" if mode == "wal" else "PRAGMA synchronous=FULL")
        with self._connections_guard:
            self._connections[key] = db
            self._busy_ms[key] = 30000
        return db

    @contextmanager
    def _db(self, timeout_seconds: float = 30.0) -> Iterator[sqlite3.Connection]:
        key = threading.get_ident()
        db = self._connection()
        milliseconds = max(50, int(max(0.05, min(30.0, float(timeout_seconds))) * 1000))
        with self._connections_guard:
            current = self._busy_ms.get(key)
        if milliseconds != current:
            db.execute(f"PRAGMA busy_timeout={milliseconds}")
            with self._connections_guard:
                self._busy_ms[key] = milliseconds

        with self._connections_guard:
            coordinated = self._writer_connections.get(key)
            if coordinated is None or not coordinated.matches(db):
                coordinated = _SQLiteWriterConnection(db, self.sqlite_writer_lock)
                self._writer_connections[key] = coordinated

        coordinated.enter_context()
        try:
            yield coordinated
        except sqlite3.Error:
            coordinated.abort_writer_transaction()
            self._drop_connection(key)
            raise
        except BaseException:
            coordinated.abort_writer_transaction()
            raise
        finally:
            coordinated.leave_context()

    def _configure_journal(self, db: sqlite3.Connection) -> None:
        """Prefere WAL e mantém DELETE como fallback quando o volume não o aceita.

        1.12.50 — com DELETE e synchronous=FULL cada escrita cria e apaga um
        journal com vários fsync, e leitor bloqueia escritor. Em disco mecânico
        isso custa dezenas de milissegundos por transação e era a causa direta
        do /health passar de 3s e derrubar o watchdog. WAL transforma a escrita
        em append sequencial e não bloqueia leitura. Nenhuma linha, tabela ou
        migration é tocada; se o volume não aceitar o arquivo -shm, o PRAGMA
        devolve o modo anterior e o caminho antigo continua valendo integralmente.
        """
        current_row = db.execute("PRAGMA journal_mode").fetchone()
        current = str(current_row[0] if current_row else "unknown").lower()

        if current != "wal":
            try:
                mode_row = db.execute("PRAGMA journal_mode=WAL").fetchone()
                current = str(mode_row[0] if mode_row else current).lower()
            except sqlite3.OperationalError as exc:
                LOG.warning("WAL indisponível neste volume (%s); mantendo o journal atual.", exc)
                current_row = db.execute("PRAGMA journal_mode").fetchone()
                current = str(current_row[0] if current_row else current).lower()

        if current == "wal":
            self.storage_journal_mode = "wal"
            db.execute("PRAGMA synchronous=NORMAL")
            db.execute("PRAGMA wal_autocheckpoint=256")
            LOG.info("Fila de telemetria em WAL; leituras deixam de bloquear a escrita.")
            return

        # PRAGMA journal_mode=DELETE exige trava exclusiva até quando o banco já
        # está em DELETE. Evitar a escrita desnecessária elimina a disputa com o painel.
        if current == "delete":
            self.storage_journal_mode = current
            db.execute("PRAGMA synchronous=FULL")
            return

        last_error: Exception | None = None
        for attempt in range(12):
            try:
                if current == "wal":
                    try:
                        db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    except sqlite3.OperationalError as exc:
                        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                            raise
                mode_row = db.execute("PRAGMA journal_mode=DELETE").fetchone()
                mode = str(mode_row[0] if mode_row else current).lower()
                self.storage_journal_mode = mode
                if mode != "delete":
                    raise sqlite3.OperationalError(f"journal SQLite incompatível: {mode}")
                db.execute("PRAGMA synchronous=FULL")
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                # Dá tempo para uma leitura curta terminar. O painel respeita o
                # marcador e deixa de abrir novas conexões durante esta janela.
                time.sleep(min(3.0, 0.25 * (attempt + 1)))
                current_row = db.execute("PRAGMA journal_mode").fetchone()
                current = str(current_row[0] if current_row else current).lower()
                if current == "delete":
                    self.storage_journal_mode = current
                    db.execute("PRAGMA synchronous=FULL")
                    return
        raise sqlite3.OperationalError(
            "Não foi possível obter acesso exclusivo para migrar a fila SQLite."
        ) from last_error


        last_error: Exception | None = None
        for attempt in range(12):
            try:
                if current == "wal":
                    try:
                        db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    except sqlite3.OperationalError as exc:
                        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                            raise
                mode_row = db.execute("PRAGMA journal_mode=DELETE").fetchone()
                mode = str(mode_row[0] if mode_row else current).lower()
                self.storage_journal_mode = mode
                if mode != "delete":
                    raise sqlite3.OperationalError(f"journal SQLite incompatível: {mode}")
                db.execute("PRAGMA synchronous=FULL")
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                message = str(exc).lower()
                if "locked" not in message and "busy" not in message:
                    raise
                # Dá tempo para uma leitura curta terminar. O painel respeita o
                # marcador e deixa de abrir novas conexões durante esta janela.
                time.sleep(min(3.0, 0.25 * (attempt + 1)))
                current_row = db.execute("PRAGMA journal_mode").fetchone()
                current = str(current_row[0] if current_row else current).lower()
                if current == "delete":
                    self.storage_journal_mode = current
                    db.execute("PRAGMA synchronous=FULL")
                    return
        raise sqlite3.OperationalError(
            "Não foi possível obter acesso exclusivo para migrar a fila SQLite."
        ) from last_error

    def _init_db(self) -> None:
        self._prepare_storage(probe=True)
        with self._journal_migration_guard():
            with self._db() as db:
                self._configure_journal(db)
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        subscription_id TEXT PRIMARY KEY,
                        environment TEXT NOT NULL,
                        account_id INTEGER NOT NULL,
                        credentials_encrypted BLOB NOT NULL,
                        vehicle_ids_json TEXT NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        status TEXT NOT NULL DEFAULT 'waiting',
                        next_run_at REAL NOT NULL,
                        last_run_at TEXT NULL,
                        last_success_at TEXT NULL,
                        last_delivery_at TEXT NULL,
                        last_error TEXT NULL,
                        last_state TEXT NULL,
                        parked_streak INTEGER NOT NULL DEFAULT 0,
                        consecutive_failures INTEGER NOT NULL DEFAULT 0,
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        active_until REAL NOT NULL DEFAULT 0,
                        interactive_until REAL NOT NULL DEFAULT 0,
                        command_until REAL NOT NULL DEFAULT 0,
                        command_key TEXT NULL,
                        command_vehicle_id TEXT NULL,
                        command_context_json TEXT NULL,
                        command_poll_count INTEGER NOT NULL DEFAULT 0,
                        command_started_at REAL NOT NULL DEFAULT 0,
                        last_presence_at TEXT NULL,
                        auth_required INTEGER NOT NULL DEFAULT 0,
                        credential_hash TEXT NULL,
                        cooldown_reason TEXT NULL,
                        last_auth_attempt_at REAL NOT NULL DEFAULT 0,
                        last_auth_success_at REAL NOT NULL DEFAULT 0,
                        config_hash TEXT NULL,
                        candidate_state TEXT NULL,
                        candidate_count INTEGER NOT NULL DEFAULT 0,
                        sleep_streak INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_subscriptions_due ON subscriptions(enabled, next_run_at);
                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        subscription_id TEXT NOT NULL,
                        environment TEXT NOT NULL,
                        account_id INTEGER NOT NULL,
                        remote_id TEXT NOT NULL,
                        source_at TEXT NOT NULL,
                        payload_encrypted BLOB NOT NULL,
                        payload_hash TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        attempts INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at REAL NOT NULL,
                        last_error TEXT NULL,
                        created_at TEXT NOT NULL,
                        delivered_at TEXT NULL,
                        FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_events_delivery ON events(status, next_attempt_at, created_at);
                    CREATE INDEX IF NOT EXISTS idx_events_subscription ON events(subscription_id, created_at);
                    CREATE TABLE IF NOT EXISTS account_auth_state (
                        environment TEXT NOT NULL,
                        account_id INTEGER NOT NULL,
                        cooldown_until REAL NOT NULL DEFAULT 0,
                        block_count INTEGER NOT NULL DEFAULT 0,
                        attempt_guard_until REAL NOT NULL DEFAULT 0,
                        last_attempt_at REAL NOT NULL DEFAULT 0,
                        last_success_at REAL NOT NULL DEFAULT 0,
                        last_origin TEXT NULL,
                        last_error TEXT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(environment, account_id)
                    );
                    """
                )
                columns = {str(row[1]) for row in db.execute("PRAGMA table_info(subscriptions)").fetchall()}
                if "cooldown_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN cooldown_until REAL NOT NULL DEFAULT 0")
                if "active_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN active_until REAL NOT NULL DEFAULT 0")
                if "interactive_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN interactive_until REAL NOT NULL DEFAULT 0")
                if "command_until" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_until REAL NOT NULL DEFAULT 0")
                if "command_key" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_key TEXT NULL")
                if "command_vehicle_id" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_vehicle_id TEXT NULL")
                if "command_context_json" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_context_json TEXT NULL")
                if "command_poll_count" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_poll_count INTEGER NOT NULL DEFAULT 0")
                if "command_started_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN command_started_at REAL NOT NULL DEFAULT 0")
                if "last_presence_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN last_presence_at TEXT NULL")
                if "auth_required" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN auth_required INTEGER NOT NULL DEFAULT 0")
                if "credential_hash" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN credential_hash TEXT NULL")
                if "cooldown_reason" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN cooldown_reason TEXT NULL")
                if "last_auth_attempt_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN last_auth_attempt_at REAL NOT NULL DEFAULT 0")
                if "last_auth_success_at" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN last_auth_success_at REAL NOT NULL DEFAULT 0")
                if "config_hash" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN config_hash TEXT NULL")
                if "candidate_state" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN candidate_state TEXT NULL")
                if "candidate_count" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN candidate_count INTEGER NOT NULL DEFAULT 0")
                if "sleep_streak" not in columns:
                    db.execute("ALTER TABLE subscriptions ADD COLUMN sleep_streak INTEGER NOT NULL DEFAULT 0")
                event_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(events)").fetchall()}
                if "sequence" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0")
                if "semantic_hash" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN semantic_hash TEXT NULL")
                if "state_changed" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN state_changed INTEGER NOT NULL DEFAULT 1")
                if "event_kind" not in event_columns:
                    db.execute("ALTER TABLE events ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'change'")
                db.executescript(
                    """
                    -- 1.12.62 — uma linha por comando aguardando veredito.
                    -- Antes a janela de confirmação morava em colunas únicas da
                    -- assinatura: o segundo comando sobrescrevia o contexto do
                    -- primeiro, que nunca recebia veredito nenhum. Aqui cada
                    -- request_id espera o seu próprio, e uma amostra de
                    -- telemetria é avaliada contra todos os pendentes.
                    CREATE TABLE IF NOT EXISTS command_confirmations (
                        confirmation_id TEXT PRIMARY KEY,
                        subscription_id TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        command_key TEXT NOT NULL,
                        command_vehicle_id TEXT NULL,
                        context_json TEXT NOT NULL,
                        started_at REAL NOT NULL,
                        expires_at REAL NOT NULL,
                        poll_count INTEGER NOT NULL DEFAULT 0,
                        evaluated_samples INTEGER NOT NULL DEFAULT 0,
                        stale_samples INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'pending',
                        resolution TEXT NULL,
                        resolved_at REAL NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_command_confirmations_pending
                        ON command_confirmations(subscription_id, status, expires_at);
                    CREATE TABLE IF NOT EXISTS vehicle_state_cache (
                        subscription_id TEXT NOT NULL,
                        remote_id TEXT NOT NULL,
                        semantic_hash TEXT NOT NULL,
                        visual_fingerprint TEXT NULL,
                        last_source_at TEXT NULL,
                        last_queued_at REAL NOT NULL DEFAULT 0,
                        sequence INTEGER NOT NULL DEFAULT 0,
                        skipped_unchanged INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(subscription_id, remote_id),
                        FOREIGN KEY(subscription_id) REFERENCES subscriptions(subscription_id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS idx_vehicle_state_updated ON vehicle_state_cache(updated_at);
                    CREATE INDEX IF NOT EXISTS idx_events_vehicle_order ON events(subscription_id, remote_id, status, sequence);
                    """
                )
                # 1.11.92 podia converter "try again in 2 minutes" em 6 horas.
                # Somente cooldowns de LOGIN com prazo absurdo são liberados;
                # limites gerais de API continuam preservados.
                now_epoch = time.time()
                repaired = db.execute(
                    "UPDATE subscriptions SET status='waiting',cooldown_until=0,next_run_at=?,"
                    "consecutive_failures=0,updated_at=? WHERE status='cooldown' "
                    "AND cooldown_until>? AND (LOWER(COALESCE(last_error,'')) LIKE '%password error limit%' "
                    "OR LOWER(COALESCE(last_error,'')) LIKE '%try again in%' "
                    "OR LOWER(COALESCE(last_error,'')) LIKE '%login attempt limit%')",
                    (now_epoch + 2, utc_iso(), now_epoch + self.login_cooldown_max_seconds),
                ).rowcount
                if repaired:
                    LOG.warning("Corrigidos %s cooldown(s) de login com prazo inválido da versão anterior.", repaired)
                # Versões anteriores também podiam manter um limite geral sem
                # Retry-After por seis horas. Ele não é removido imediatamente:
                # é reduzido para uma reavaliação única e segura em cinco minutos.
                repaired_general = db.execute(
                    "UPDATE subscriptions SET cooldown_until=?,next_run_at=?,updated_at=? "
                    "WHERE status='cooldown' AND cooldown_until>? "
                    "AND LOWER(COALESCE(last_error,'')) NOT LIKE '%password error limit%' "
                    "AND LOWER(COALESCE(last_error,'')) NOT LIKE '%try again in%' "
                    "AND LOWER(COALESCE(last_error,'')) NOT LIKE '%login attempt limit%'",
                    (now_epoch + 300, now_epoch + 300, utc_iso(), now_epoch + 3600),
                ).rowcount
                if repaired_general:
                    LOG.warning("Reduzidos %s cooldown(s) gerais antigos para reavaliação segura em 300s.", repaired_general)

    @staticmethod
    def _account_id(payload_or_id: dict[str, Any] | int) -> int:
        try:
            if isinstance(payload_or_id, dict):
                return int(payload_or_id.get("account_id") or 0)
            return int(payload_or_id or 0)
        except (TypeError, ValueError):
            return 0

    def account_auth_status(self, environment: str, payload_or_id: dict[str, Any] | int) -> dict[str, Any]:
        account_id = self._account_id(payload_or_id)
        if account_id < 1:
            return {"managed": False, "account_id": 0, "cooldown": False, "retry_after_seconds": 0}
        now_epoch = time.time()
        # 1.12.82 — consulta somente-leitura. WAL/SQLite já fornece snapshot
        # consistente; segurar `self.lock` aqui fazia um comando esperar uma
        # escrita/entrega de telemetria antes mesmo de tentar a trava da conta.
        # Reservas e mutações de autenticação continuam usando BEGIN IMMEDIATE
        # sob `self.lock` em begin_account_auth/record_*; só a leitura sai do lock.
        with self._db() as db:
            row = db.execute(
                "SELECT cooldown_until,attempt_guard_until,block_count,last_origin,last_error,last_attempt_at,last_success_at "
                "FROM account_auth_state WHERE environment=? AND account_id=? LIMIT 1",
                (str(environment or ""), account_id),
            ).fetchone()
        if row is None:
            return {"managed": True, "account_id": account_id, "cooldown": False, "retry_after_seconds": 0}
        blocked_until = max(float(row["cooldown_until"] or 0), float(row["attempt_guard_until"] or 0))
        return {
            "managed": True,
            "account_id": account_id,
            "cooldown": blocked_until > now_epoch,
            "retry_after_seconds": max(0, int(blocked_until - now_epoch)),
            "block_count": int(row["block_count"] or 0),
            "last_origin": str(row["last_origin"] or ""),
            "last_error": connector.clean_message(str(row["last_error"] or "")),
            "last_attempt_at": float(row["last_attempt_at"] or 0),
            "last_success_at": float(row["last_success_at"] or 0),
        }

    def assert_account_cloud_allowed(self, environment: str, payload_or_id: dict[str, Any] | int, origin: str) -> None:
        status = self.account_auth_status(environment, payload_or_id)
        if status.get("cooldown"):
            previous = str(status.get("last_origin") or "outra origem")[:80]
            raise connector.ConnectorLoginCooldownError(
                f"Cooldown global ativo para esta conta; origem anterior={previous}, origem atual={str(origin or 'unknown')[:80]}.",
                max(30, int(status.get("retry_after_seconds") or 30)),
            )

    def begin_account_auth(self, environment: str, payload_or_id: dict[str, Any] | int, origin: str) -> dict[str, Any]:
        """Reserve atomically the only login attempt allowed for an account."""
        account_id = self._account_id(payload_or_id)
        if account_id < 1:
            return {"managed": False, "account_id": 0, "origin": str(origin or "unknown")[:80]}
        environment = str(environment or "")
        origin = str(origin or "unknown")[:80]
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT cooldown_until,attempt_guard_until,block_count,last_origin FROM account_auth_state "
                    "WHERE environment=? AND account_id=? LIMIT 1",
                    (environment, account_id),
                ).fetchone()
                blocked_until = 0.0
                previous_origin = "outra origem"
                if row is not None:
                    blocked_until = max(float(row["cooldown_until"] or 0), float(row["attempt_guard_until"] or 0))
                    previous_origin = str(row["last_origin"] or previous_origin)
                if blocked_until > now_epoch:
                    db.execute("ROLLBACK")
                    raise connector.ConnectorLoginCooldownError(
                        f"Autenticação global protegida: {previous_origin} já reservou a tentativa desta conta; origem atual={origin}.",
                        max(30, int(blocked_until - now_epoch)),
                    )
                db.execute(
                    "INSERT INTO account_auth_state(environment,account_id,cooldown_until,block_count,attempt_guard_until,last_attempt_at,last_success_at,last_origin,last_error,updated_at) "
                    "VALUES(?,?,0,0,?,?,0,?,NULL,?) "
                    "ON CONFLICT(environment,account_id) DO UPDATE SET attempt_guard_until=excluded.attempt_guard_until,"
                    "last_attempt_at=excluded.last_attempt_at,last_origin=excluded.last_origin,last_error=NULL,updated_at=excluded.updated_at",
                    (environment, account_id, now_epoch + 240, now_epoch, origin, now_iso),
                )
                db.execute("COMMIT")
            except Exception:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        LOG.info("Autenticação reservada para conta=%s origem=%s; tentativas paralelas foram bloqueadas.", account_id, origin)
        return {"managed": True, "account_id": account_id, "origin": origin}

    def record_account_auth_success(self, environment: str, payload_or_id: dict[str, Any] | int, origin: str = "success") -> None:
        account_id = self._account_id(payload_or_id)
        if account_id < 1:
            return
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "INSERT INTO account_auth_state(environment,account_id,cooldown_until,block_count,attempt_guard_until,last_attempt_at,last_success_at,last_origin,last_error,updated_at) "
                "VALUES(?,?,0,0,0,0,?,?,NULL,?) "
                "ON CONFLICT(environment,account_id) DO UPDATE SET cooldown_until=0,block_count=0,attempt_guard_until=0,"
                "last_success_at=excluded.last_success_at,last_origin=excluded.last_origin,last_error=NULL,updated_at=excluded.updated_at",
                (str(environment or ""), account_id, now_epoch, str(origin or "success")[:80], now_iso),
            )
        self._clear_account_subscription_cooldown(environment, account_id)

    def record_account_auth_failure(
        self,
        environment: str,
        payload_or_id: dict[str, Any] | int,
        origin: str,
        message: str,
        retry_after_seconds: int = 300,
        blocked: bool = False,
    ) -> int:
        account_id = self._account_id(payload_or_id)
        requested = max(30, int(retry_after_seconds or 300))
        if account_id < 1:
            return min(self.login_cooldown_max_seconds, requested)
        environment = str(environment or "")
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT block_count FROM account_auth_state WHERE environment=? AND account_id=? LIMIT 1",
                (environment, account_id),
            ).fetchone()
            previous = int(row["block_count"] or 0) if row is not None else 0
            block_count = min(len(self.login_backoff_schedule), previous + 1) if blocked else previous
            progressive = self.login_backoff_schedule[max(0, block_count - 1)] if blocked else min(240, requested)
            delay = max(requested, progressive)
            delay = max(30, min(self.login_cooldown_max_seconds, delay))
            until = now_epoch + delay
            db.execute(
                "INSERT INTO account_auth_state(environment,account_id,cooldown_until,block_count,attempt_guard_until,last_attempt_at,last_success_at,last_origin,last_error,updated_at) "
                "VALUES(?,?,?,?,0,?,0,?,?,?) "
                "ON CONFLICT(environment,account_id) DO UPDATE SET cooldown_until=excluded.cooldown_until,block_count=excluded.block_count,"
                "attempt_guard_until=0,last_origin=excluded.last_origin,last_error=excluded.last_error,updated_at=excluded.updated_at",
                (environment, account_id, until, block_count, now_epoch, str(origin or "unknown")[:80], connector.clean_message(message)[:500], now_iso),
            )
        self._apply_account_subscription_cooldown(environment, account_id, delay, message, "login" if blocked else "auth_guard")
        return delay

    def _apply_account_subscription_cooldown(
        self, environment: str, account_id: int, delay: int, message: str, reason: str
    ) -> None:
        until = time.time() + max(30, int(delay))
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET status='cooldown',cooldown_until=?,cooldown_reason=?,next_run_at=?,last_error=?,updated_at=? "
                "WHERE environment=? AND account_id=?",
                (until, str(reason or "login")[:40], until, connector.clean_message(message)[:500], now, str(environment or ""), int(account_id or 0)),
            )
        self.wake_event.set()

    def _clear_account_subscription_cooldown(self, environment: str, account_id: int) -> None:
        if int(account_id or 0) < 1:
            return
        now = utc_iso()
        with self.lock, self._db() as db:
            db.execute(
                "UPDATE subscriptions SET cooldown_until=0,cooldown_reason=NULL,status=CASE WHEN status='cooldown' THEN 'waiting' ELSE status END,"
                "next_run_at=CASE WHEN status='cooldown' THEN MIN(next_run_at,?) ELSE next_run_at END,"
                "last_error=CASE WHEN status='cooldown' THEN NULL ELSE last_error END,updated_at=? "
                "WHERE environment=? AND account_id=?",
                (time.time() + 2, now, str(environment or ""), int(account_id or 0)),
            )
        self.wake_event.set()

    @staticmethod
    def _try_refresh_client_session(client: Any) -> bool:
        """Try one logical refresh without multiplying cloud requests.

        Some leapmotor-api releases expose the same refresh implementation under
        multiple aliases. Calling every alias after a timeout, rate limit or
        cooldown could turn one recovery attempt into three cloud requests.
        Explicit ``False`` may fall through to another distinct implementation;
        any exception is classified once and stops the chain.
        """
        seen: set[tuple[int, int]] = set()
        # 1.12.53 — "token_refresh" é o nome real na leapmotor-api ("token refresh
        # is handled automatically (...) see token_refresh() for manual control").
        # Faltando da lista, nenhuma renovação acontecia e toda sessão vencida
        # caía direto no login completo, que custa de 5 a 18 s por conta.
        for method_name in ("token_refresh", "refresh_session", "refresh_token", "refresh"):
            method = getattr(client, method_name, None)
            if not callable(method):
                continue
            owner = getattr(method, "__self__", None)
            function = getattr(method, "__func__", method)
            identity = (id(owner), id(function))
            if identity in seen:
                continue
            seen.add(identity)
            try:
                result = method()
            except connector.ConnectorLoginCooldownError:
                raise
            except connector.ConnectorTemporaryError:
                raise
            except connector.ConnectorAuthenticationError:
                return False
            except Exception as exc:  # noqa: BLE001
                message = connector.clean_message(str(exc))
                cooldown = connector.login_cooldown_seconds(exc)
                if cooldown > 0:
                    raise connector.ConnectorLoginCooldownError(message, cooldown) from exc
                if connector.is_transient_cloud_error(exc):
                    raise connector.ConnectorTemporaryError(message) from exc
                LOG.info("Refresh de sessão por %s não foi aceito: %s", method_name, message)
                return False
            if result is not False:
                return True
        return False

    def execute_driving_record_probe(
        self,
        environment: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run one low-priority Official read on an already-open account session.

        This path never creates/login/refreshes a client and never retries the
        cloud request. Discovery is read-only and bounded; lock order follows the
        telemetry/modern command architecture: account -> global slot -> session.
        A manual command is rechecked at every boundary and wins before network.
        """
        try:
            from leaphub_official_trip_probe import normalize_window, probe_windowed_mileage_energy
        except ModuleNotFoundError:
            from official_trip_probe import normalize_window, probe_windowed_mileage_energy

        overall_started = time.monotonic()
        account_id = self._account_id(payload)
        if account_id < 1:
            raise ValueError("Conta inválida para a sonda de histórico.")
        begin_ms, end_ms = normalize_window(payload)
        vehicle_id = str(payload.get("vehicle_id") or "").strip()[:190]
        direct_vin = str(payload.get("vehicle_vin") or "").strip().upper()
        if direct_vin and (len(direct_vin) != 17 or not direct_vin.isalnum()):
            raise ValueError("Identificador VIN inválido para a sonda de histórico.")

        operation_payload: dict[str, Any] = {"account_id": account_id}
        if vehicle_id:
            operation_payload["vehicle_id"] = vehicle_id

        def deferred(reason: str, retry: int = 5, **extra: Any) -> dict[str, Any]:
            result = {
                "ok": False, "temporary": True, "low_priority": True, "reason": reason,
                "retry_after_seconds": max(2, min(30, int(retry))),
                "message": "A leitura oficial cedeu prioridade ao fluxo principal e poderá ser tentada depois.",
                "engine_version": ENGINE_VERSION, "connector_version": connector.CONNECTOR_VERSION,
                "library_version": connector.package_version(), "raw_values_included": False, "mapped_fields": [],
                "total_ms": int(round((time.monotonic() - overall_started) * 1000)),
            }
            result.update(extra)
            return result

        manual = self.manual_pending_provider
        if manual is not None and manual(environment, operation_payload):
            return deferred("manual_priority")

        # Do not use self._db here: on a new request thread its persistent
        # connection starts with a 30s busy timeout before _db can shorten it.
        # Official uses an independent read-only connection whose timeout is
        # bounded from the moment it is opened, then closes it immediately.
        probe_db = None
        try:
            probe_uri = self.db_path.resolve().as_uri() + "?mode=ro"
            probe_db = sqlite3.connect(probe_uri, uri=True, timeout=0.15)
            probe_db.row_factory = sqlite3.Row
            probe_db.execute("PRAGMA busy_timeout=150")
            probe_db.execute("PRAGMA query_only=ON")
            auth_row = probe_db.execute(
                "SELECT cooldown_until,attempt_guard_until FROM account_auth_state "
                "WHERE environment=? AND account_id=? LIMIT 1",
                (str(environment or ""), account_id),
            ).fetchone()
            rows = list(probe_db.execute(
                "SELECT subscription_id,vehicle_ids_json FROM subscriptions "
                "WHERE environment=? AND account_id=? AND enabled=1 ORDER BY updated_at DESC LIMIT 32",
                (str(environment or ""), account_id),
            ).fetchall())
        except (OSError, sqlite3.Error):
            return deferred("subscription_store_busy", 5)
        finally:
            if probe_db is not None:
                probe_db.close()

        now_epoch = time.time()
        if auth_row is not None:
            blocked_until = max(float(auth_row["cooldown_until"] or 0), float(auth_row["attempt_guard_until"] or 0))
            if blocked_until > now_epoch:
                return deferred("account_cooldown", max(2, min(30, int(blocked_until - now_epoch))))
        if not rows:
            return deferred("subscription_not_ready", 15)

        target: tuple[str, Any, Any, str, str, set[str]] | None = None
        implicit_targets: dict[tuple[str, str], tuple[str, Any, Any, str, str, set[str]]] = {}
        vehicle_id_authorized = False
        ready_sessions = 0
        for row in rows:
            subscription_id = str(row["subscription_id"] or "")
            try:
                decoded_ids = json.loads(str(row["vehicle_ids_json"] or "[]"))
                authorized_ids = {str(item).strip()[:190] for item in decoded_ids if str(item).strip()} if isinstance(decoded_ids, list) else set()
            except (TypeError, ValueError, json.JSONDecodeError):
                authorized_ids = set()
            if vehicle_id and vehicle_id in authorized_ids:
                vehicle_id_authorized = True
            with self.session_lock:
                session = self.sessions.get(subscription_id)
            if not isinstance(session, dict) or session.get("client") is None:
                continue
            ready_sessions += 1
            client = session["client"]
            vehicles = session.get("vehicles") if isinstance(session.get("vehicles"), list) else []
            candidates: list[tuple[Any, str, str]] = []
            for item in vehicles:
                remote_id = str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "") or "").strip()[:190]
                vin = str(connector.attribute(item, "vin", "") or "").strip().upper()
                if not remote_id or remote_id not in authorized_ids:
                    continue
                if len(vin) != 17 or not vin.isalnum():
                    continue
                if vehicle_id and remote_id != vehicle_id:
                    continue
                if direct_vin and vin != direct_vin:
                    continue
                candidates.append((item, remote_id, vin))
            if vehicle_id or direct_vin:
                if len(candidates) == 1:
                    _item, remote_id, vin = candidates[0]
                    target = (subscription_id, session, client, remote_id, vin, authorized_ids)
                    break
                if len(candidates) > 1:
                    raise ValueError("A sessão retornou mais de um alvo para os identificadores informados.")
            else:
                for _item, remote_id, vin in candidates:
                    implicit_targets.setdefault(
                        (remote_id, vin),
                        (subscription_id, session, client, remote_id, vin, authorized_ids),
                    )

        if target is None and not vehicle_id and not direct_vin:
            if len(implicit_targets) == 1:
                target = next(iter(implicit_targets.values()))
            elif len(implicit_targets) > 1:
                raise ValueError("Informe o veículo para uma conta com mais de um veículo autorizado.")

        if target is None:
            if vehicle_id and not vehicle_id_authorized:
                raise ValueError("O veículo informado não pertence ao escopo autorizado desta assinatura.")
            return deferred("session_not_ready" if ready_sessions == 0 else "vehicle_not_cached", 15)

        subscription_id, expected_session, client, remote_id, vin, authorized_ids = target
        if self.account_lock_provider is None:
            return deferred("account_lock_unavailable", 15)

        account_lock: Any | None = None
        account_acquired = False
        slot_acquired = False
        session_acquired = False
        account_wait_ms = 0
        slot_wait_ms = 0
        session_wait_ms = 0
        session_operation_lock = self._session_operation_lock(subscription_id)
        try:
            account_lock = self.account_lock_provider(environment, operation_payload)
            wait_started = time.monotonic()
            account_acquired = account_lock.acquire(timeout=0.10)
            account_wait_ms = int(round((time.monotonic() - wait_started) * 1000))
            if not account_acquired:
                return deferred("account_busy", 5, account_wait_ms=account_wait_ms)
            if manual is not None and manual(environment, operation_payload):
                return deferred("manual_priority", account_wait_ms=account_wait_ms)

            wait_started = time.monotonic()
            slot_acquired = self.operation_semaphore.acquire(timeout=0.10)
            slot_wait_ms = int(round((time.monotonic() - wait_started) * 1000))
            if not slot_acquired:
                return deferred("connector_busy", 5, account_wait_ms=account_wait_ms, connector_slot_ms=slot_wait_ms)
            if manual is not None and manual(environment, operation_payload):
                return deferred("manual_priority", account_wait_ms=account_wait_ms, connector_slot_ms=slot_wait_ms)

            wait_started = time.monotonic()
            session_acquired = session_operation_lock.acquire(timeout=0.10)
            session_wait_ms = int(round((time.monotonic() - wait_started) * 1000))
            if not session_acquired:
                return deferred(
                    "session_busy", 5, account_wait_ms=account_wait_ms,
                    connector_slot_ms=slot_wait_ms, session_wait_ms=session_wait_ms,
                )
            if manual is not None and manual(environment, operation_payload):
                return deferred(
                    "manual_priority", account_wait_ms=account_wait_ms,
                    connector_slot_ms=slot_wait_ms, session_wait_ms=session_wait_ms,
                )

            # TOCTOU guard: the exact session/client and authorization must still
            # be current after all locks were acquired but before network I/O.
            with self.session_lock:
                current = self.sessions.get(subscription_id)
            if not isinstance(current, dict) or current is not expected_session or current.get("client") is not client:
                return deferred("session_changed", 5)
            current_vehicles = current.get("vehicles") if isinstance(current.get("vehicles"), list) else []
            target_still_cached = any(
                str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "") or "").strip()[:190] == remote_id
                and str(connector.attribute(item, "vin", "") or "").strip().upper() == vin
                for item in current_vehicles
            )
            if not target_still_cached:
                return deferred("vehicle_cache_changed", 5)
            live_db = None
            try:
                live_uri = self.db_path.resolve().as_uri() + "?mode=ro"
                live_db = sqlite3.connect(live_uri, uri=True, timeout=0.10)
                live_db.row_factory = sqlite3.Row
                live_db.execute("PRAGMA busy_timeout=100")
                live_db.execute("PRAGMA query_only=ON")
                live = live_db.execute(
                    "SELECT enabled,vehicle_ids_json FROM subscriptions WHERE subscription_id=? LIMIT 1",
                    (subscription_id,),
                ).fetchone()
            except (OSError, sqlite3.Error):
                return deferred("subscription_store_busy", 5)
            finally:
                if live_db is not None:
                    live_db.close()
            if live is None or int(live["enabled"] or 0) != 1:
                return deferred("subscription_changed", 5)
            try:
                live_ids_value = json.loads(str(live["vehicle_ids_json"] or "[]"))
                live_ids = {str(item).strip()[:190] for item in live_ids_value if str(item).strip()} if isinstance(live_ids_value, list) else set()
            except (TypeError, ValueError, json.JSONDecodeError):
                live_ids = set()
            if remote_id not in live_ids or remote_id not in authorized_ids:
                raise ValueError("O veículo deixou de pertencer ao escopo autorizado desta assinatura.")
            if manual is not None and manual(environment, operation_payload):
                return deferred("manual_priority")

            try:
                with self._telemetry_request_timeout(client):
                    result = probe_windowed_mileage_energy(client, vin=vin, begin_ms=begin_ms, end_ms=end_ms)
            except Exception as exc:  # noqa: BLE001
                elapsed_ms = int(round((time.monotonic() - overall_started) * 1000))
                if connector.is_transient_cloud_error(exc):
                    LOG.info("Sonda oficial de %s cedeu após falha temporária em %sms; sem retry e sem corpo bruto.", subscription_id, elapsed_ms)
                    return deferred("cloud_temporary", 20)
                LOG.warning("Sonda oficial de %s falhou em %sms; resposta bruta omitida; tipo=%s.", subscription_id, elapsed_ms, type(exc).__name__)
                return {
                    "ok": False, "temporary": False, "low_priority": True, "reason": "probe_failed",
                    "message": "A nuvem recusou a sonda oficial; nenhum valor bruto foi exposto.",
                    "engine_version": ENGINE_VERSION, "connector_version": connector.CONNECTOR_VERSION,
                    "library_version": connector.package_version(), "raw_values_included": False, "mapped_fields": [],
                    "total_ms": elapsed_ms,
                }
            current["last_used_at"] = time.time()
            result.update({
                "low_priority": True, "session_reused": True, "engine_version": ENGINE_VERSION,
                "connector_version": connector.CONNECTOR_VERSION, "library_version": connector.package_version(),
                "bounded_timeout_seconds": float(self.telemetry_network_timeout_seconds),
                "latency_ms": {
                    "account_wait": account_wait_ms,
                    "connector_slot_wait": slot_wait_ms,
                    "session_wait": session_wait_ms,
                    "total": int(round((time.monotonic() - overall_started) * 1000)),
                },
            })
            return result
        finally:
            if session_acquired:
                session_operation_lock.release()
            if slot_acquired:
                self.operation_semaphore.release()
            if account_acquired and account_lock is not None:
                account_lock.release()
    def execute_account_operation(self, environment: str, payload: dict[str, Any], sync: bool, origin: str) -> dict[str, Any]:
        """Execute account test/sync under the persistent account auth coordinator."""
        account_id = self._account_id(payload)
        self.assert_account_cloud_allowed(environment, payload, origin)

        # Reutilize a sessão da telemetria quando ela pertence às mesmas
        # credenciais. Assim sincronizar não cria um segundo token apenas para
        # consultar os mesmos veículos.
        subscription_id = ""
        credentials_value = payload.get("credentials") if sync else payload
        credentials = credentials_value if isinstance(credentials_value, dict) else {}
        expected_hash = hashlib.sha256(canonical_json(credentials)).hexdigest() if credentials else ""
        if account_id > 0:
            with self.lock, self._db() as db:
                row = db.execute(
                    "SELECT subscription_id,credentials_encrypted FROM subscriptions WHERE environment=? AND account_id=? AND enabled=1 "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (str(environment or ""), account_id),
                ).fetchone()
            subscription_id = str(row["subscription_id"] or "") if row is not None else ""
            if row is not None and credentials:
                try:
                    stored_credentials = json.loads(
                        self.fernet.decrypt(bytes(row["credentials_encrypted"])).decode("utf-8")
                    )
                    required = ("email", "password", "certificate_pem", "private_key_pem")
                    if isinstance(stored_credentials, dict) and all(
                        str(stored_credentials.get(key) or "") == str(credentials.get(key) or "")
                        for key in required
                    ):
                        expected_hash = str(self.sessions.get(subscription_id, {}).get("credential_hash") or expected_hash)
                except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
                    pass
        if subscription_id:
            with self._session_operation_lock(subscription_id):
                with self.session_lock:
                    session = self.sessions.get(subscription_id)
                if (
                    isinstance(session, dict)
                    and session.get("client") is not None
                    and expected_hash
                    and session.get("credential_hash") == expected_hash
                ):
                    try:
                        cached_for_operation = None
                        if sync and str(payload.get("vehicle_id") or "").strip():
                            cached_value = session.get("vehicles")
                            cached_at = float(session.get("vehicles_cached_at") or 0)
                            if isinstance(cached_value, list) and cached_value and time.time() - cached_at < self.vehicle_list_cache_seconds:
                                cached_for_operation = cached_value
                        result = connector.handle_account(
                            payload, sync=sync, borrowed_client=session["client"],
                            borrowed_vehicles=cached_for_operation,
                        )
                        session["last_used_at"] = time.time()
                        if isinstance(result.get("vehicles"), list):
                            # serialized vehicles are not suitable as library objects;
                            # keep the original borrowed list already stored.
                            pass
                        self.record_account_auth_success(environment, payload, origin + "_session")
                        return result
                    except connector.ConnectorAuthenticationError:
                        try:
                            refreshed = self._try_refresh_client_session(session["client"])
                        except connector.ConnectorLoginCooldownError as exc:
                            self._close_session_locked(subscription_id)
                            delay = self.record_account_auth_failure(
                                environment, payload, origin + "_refresh", str(exc), exc.retry_after_seconds, blocked=True
                            )
                            raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
                        except connector.ConnectorTemporaryError as exc:
                            session["last_used_at"] = time.time()
                            self.record_account_auth_failure(
                                environment, payload, origin + "_refresh", str(exc), 60, blocked=False
                            )
                            raise connector.ConnectorTemporaryError(str(exc)) from exc
                        if refreshed:
                            try:
                                cached_for_operation = None
                                if sync and str(payload.get("vehicle_id") or "").strip():
                                    cached_value = session.get("vehicles")
                                    cached_at = float(session.get("vehicles_cached_at") or 0)
                                    if isinstance(cached_value, list) and cached_value and time.time() - cached_at < self.vehicle_list_cache_seconds:
                                        cached_for_operation = cached_value
                                result = connector.handle_account(
                                    payload, sync=sync, borrowed_client=session["client"],
                                    borrowed_vehicles=cached_for_operation,
                                )
                                session["last_used_at"] = time.time()
                                self.record_account_auth_success(environment, payload, origin + "_refresh")
                                return result
                            except connector.ConnectorLoginCooldownError as exc:
                                self._close_session_locked(subscription_id)
                                delay = self.record_account_auth_failure(
                                    environment, payload, origin, str(exc), exc.retry_after_seconds, blocked=True
                                )
                                raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
                            except connector.ConnectorAuthenticationError:
                                # O refresh não recuperou a sessão. Feche somente
                                # esta sessão e siga para uma única autenticação
                                # coordenada, sem deixar o cliente inválido em uso.
                                self._close_session_locked(subscription_id)
                            except connector.ConnectorTemporaryError as exc:
                                self.record_account_auth_failure(
                                    environment, payload, origin, str(exc), 60, blocked=False
                                )
                                raise connector.ConnectorTemporaryError(str(exc)) from exc
                        else:
                            self._close_session_locked(subscription_id)
                    except connector.ConnectorLoginCooldownError as exc:
                        delay = self.record_account_auth_failure(
                            environment, payload, origin, str(exc), exc.retry_after_seconds, blocked=True
                        )
                        raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
                    except connector.ConnectorTemporaryError as exc:
                        self.record_account_auth_failure(
                            environment, payload, origin, str(exc), 60, blocked=False
                        )
                        raise connector.ConnectorTemporaryError(str(exc)) from exc

        reservation = self.begin_account_auth(environment, payload, origin)
        try:
            result = connector.handle_account(payload, sync=sync)
            self.record_account_auth_success(environment, payload, origin)
            return result
        except connector.ConnectorLoginCooldownError as exc:
            delay = self.record_account_auth_failure(
                environment, payload, origin, str(exc), exc.retry_after_seconds, blocked=True
            )
            raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
        except connector.ConnectorTemporaryError as exc:
            if reservation.get("managed"):
                self.record_account_auth_failure(environment, payload, origin, str(exc), 60, blocked=False)
                raise connector.ConnectorTemporaryError(str(exc)) from exc
            raise
        except Exception:
            if reservation.get("managed"):
                self.record_account_auth_failure(environment, payload, origin, "Falha de autenticação ou sincronização.", 60, blocked=False)
            raise

    def _set_account_login_cooldown(self, environment: str, account_id: int, retry_after_seconds: int, message: str) -> None:
        self.record_account_auth_failure(
            environment, account_id, "legacy", message, retry_after_seconds, blocked=True
        )

    def _clear_account_login_cooldown(self, environment: str, account_id: int) -> None:
        self.record_account_auth_success(environment, account_id, "session_ok")

    def _execute_isolated_command(
        self,
        environment: str,
        payload: dict[str, Any],
        account_id: int,
        progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        self.begin_account_auth(environment, account_id, "command")
        try:
            result = connector.handle_command(payload, progress=progress)
            self.record_account_auth_success(environment, account_id, "command")
            return result
        except connector.ConnectorLoginCooldownError as exc:
            delay = self.record_account_auth_failure(
                environment, account_id, "command", str(exc), exc.retry_after_seconds, blocked=True
            )
            raise connector.ConnectorLoginCooldownError(str(exc), delay) from exc
        except connector.ConnectorTemporaryError as exc:
            self.record_account_auth_failure(environment, account_id, "command", str(exc), 60, blocked=False)
            raise connector.ConnectorTemporaryError(str(exc)) from exc
        except Exception:
            self.record_account_auth_failure(
                environment, account_id, "command", "Falha durante autenticação de comando.", 60, blocked=False
            )
            raise

    def _create_persistent_session_locked(
        self,
        subscription_id: str,
        environment: str,
        account_id: int,
        credentials: dict[str, Any],
        origin: str,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Authenticate once and retain the client for commands and FAST telemetry.

        The caller must hold the subscription operation lock. Keeping the client
        created for a manual command prevents the confirmation cycle from opening
        a second Leapmotor login immediately after the action was accepted.
        """
        now_epoch = time.time()
        credential_hash = hashlib.sha256(canonical_json(credentials)).hexdigest()
        if manual_should_yield is not None and manual_should_yield():
            raise TelemetryYieldForManual("Operação manual aguardando antes da autenticação automática.")

        temp_dir = connector.secure_temp_directory()
        client = None
        try:
            create_client_started = time.monotonic()
            try:
                client = connector.create_client(
                    credentials,
                    temp_dir,
                    None,
                # 1.12.71 — o cliente nasce com o tempo limite da TELEMETRIA, que
                # é quem segura a trava da conta durante a chamada. Os segundos
                # a mais de que o despacho precisa são emprestados só a ele, em
                # `_dispatch_timeout`. A 1.12.70 elevava o cliente inteiro, e
                # isso alongava a espera de quem manda o comando seguinte.
                    request_timeout_seconds=(
                        self.telemetry_network_timeout_seconds
                        if origin == "telemetry"
                        else self.request_timeout_seconds
                    ),
                )
            finally:
                log_slow_telemetry_stage(subscription_id, "session_create_client", create_client_started, origin=origin)
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual recebeu prioridade antes do login automático.")

            auth_reservation_started = time.monotonic()
            try:
                self.begin_account_auth(environment, account_id, origin)
            finally:
                log_slow_telemetry_stage(subscription_id, "session_auth_reservation", auth_reservation_started, origin=origin)

            auth_attempt_write_started = time.monotonic()
            try:
                with self.lock, self._db() as db:
                    db.execute(
                        "UPDATE subscriptions SET last_auth_attempt_at=?,updated_at=? WHERE subscription_id=?",
                        (time.time(), utc_iso(), subscription_id),
                    )
            finally:
                log_slow_telemetry_stage(subscription_id, "session_auth_attempt_write", auth_attempt_write_started, origin=origin)

            login_started = time.monotonic()
            try:
                client.login()
            finally:
                log_slow_telemetry_stage(subscription_id, "session_login", login_started, origin=origin)

            auth_success_started = time.monotonic()
            try:
                self.record_account_auth_success(environment, account_id, origin)
            finally:
                log_slow_telemetry_stage(subscription_id, "session_auth_success_bookkeeping", auth_success_started, origin=origin)

            auth_success_write_started = time.monotonic()
            try:
                with self.lock, self._db() as db:
                    db.execute(
                        "UPDATE subscriptions SET last_auth_success_at=?,cooldown_reason=NULL,updated_at=? WHERE subscription_id=?",
                        (time.time(), utc_iso(), subscription_id),
                    )
            finally:
                log_slow_telemetry_stage(subscription_id, "session_auth_success_write", auth_success_write_started, origin=origin)
        except Exception as exc:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(exc, TelemetryYieldForManual):
                raise
            delay = connector.login_cooldown_seconds(exc)
            if delay > 0:
                protected_delay = self.record_account_auth_failure(
                    environment,
                    account_id,
                    origin,
                    str(exc),
                    delay,
                    blocked=True,
                )
                raise connector.ConnectorLoginCooldownError(
                    "A Leapmotor limitou temporariamente novas autenticações. A próxima tentativa respeitará o cooldown global.",
                    protected_delay,
                ) from exc
            if connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError):
                self.record_account_auth_failure(environment, account_id, origin, str(exc), 60, blocked=False)
            else:
                self.record_account_auth_failure(
                    environment,
                    account_id,
                    origin,
                    "Falha de autenticação.",
                    60,
                    blocked=False,
                )
            raise

        session = {
            "client": client,
            "temp_dir": temp_dir,
            "credential_hash": credential_hash,
            "created_at": now_epoch,
            "last_used_at": now_epoch,
            "vehicles": [],
            "vehicles_cached_at": 0.0,
            "messages": [],
            "messages_cached_at": 0.0,
            # O primeiro ciclo após comando continua FAST. SLOW não disputa
            # a confirmação do estado físico.
            "slow_last_at": now_epoch,
        }
        with self.session_lock:
            self.sessions[subscription_id] = session
        LOG.info(
            "Sessão Leapmotor criada para %s por %s; será reutilizada pela próxima leitura FAST.",
            subscription_id,
            origin,
        )
        return session

    def execute_command(
        self,
        environment: str,
        payload: dict[str, Any],
        progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
    ) -> dict[str, Any]:
        """Executa a ação sob a mesma sessão e trava usadas pela telemetria.

        Uma sessão válida nunca é destruída apenas porque o usuário acionou um
        comando. Se não houver sessão ativa, o cliente autenticado pelo comando
        fica retido para a confirmação FAST. Falhas transitórias preservam a
        sessão e nenhuma ação aceita pela nuvem é repetida automaticamente.
        """
        try:
            account_id = int(payload.get("account_id") or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id < 1:
            return connector.handle_command(payload, progress=progress)

        # 1.12.56 — nada entre a entrada do método e a trava de sessão tinha
        # contador. Com session_wait/login/prepare/verification todos em 0 e o
        # dispatch em ~4s, comandos de 94s deixavam 90s sem atribuição nenhuma.
        engine_started = time.monotonic()
        self.assert_account_cloud_allowed(environment, account_id, "command")
        auth_status_ms = int(round((time.monotonic() - engine_started) * 1000))

        # 1.12.91 — este SELECT é somente-leitura e não participa das mutações
        # protegidas por `self.lock`. A trava global fazia qualquer conta bloquear
        # qualquer outra: o log de campo mediu 12.292s em `trava_motor`, enquanto
        # a trava da conta levou 1ms e o dispatch 612ms. `account_auth_status` já
        # usa o mesmo princípio desde 1.12.82. Mantemos `engine_lock_wait_ms=0`
        # para compatibilidade do diagnóstico e damos teto próprio ao SQLite.
        engine_lock_wait_ms = 0
        subscription_read_started = time.monotonic()
        try:
            with self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS) as db:
                row = db.execute(
                    "SELECT subscription_id,cooldown_until,status FROM subscriptions "
                    "WHERE environment=? AND account_id=? AND enabled=1 "
                    "ORDER BY updated_at DESC LIMIT 1",
                    (str(environment or ""), account_id),
                ).fetchone()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise connector.ConnectorTemporaryError(
                    "A fila local de telemetria não liberou a leitura de assinatura a tempo. "
                    "O comando não foi enviado ao veículo e continua na fila."
                ) from exc
            raise
        subscription_read_ms = int(round((time.monotonic() - subscription_read_started) * 1000))
        if row is None:
            return self._execute_isolated_command(environment, payload, account_id, progress)

        subscription_id = str(row["subscription_id"] or "")
        if not subscription_id:
            return self._execute_isolated_command(environment, payload, account_id, progress)
        cooldown_until = float(row["cooldown_until"] or 0)
        if cooldown_until > time.time():
            raise connector.ConnectorLoginCooldownError(
                "A Leapmotor limitou temporariamente novas autenticações. O comando continua protegido na fila.",
                max(30, int(cooldown_until - time.time())),
            )

        # 1.12.50 — a espera pela trava de sessão e a autenticação feitas aqui
        # não tinham contador: ficavam dentro de remote_execute_ms sem aparecer
        # em nenhuma fase, e session_prepare_ms mede apenas o open_client() do
        # conector, que é ~0ms com cliente emprestado.
        session_wait_started = time.monotonic()
        engine_precheck_ms = int(round((session_wait_started - engine_started) * 1000))
        with self._session_operation_lock(subscription_id):
            session_wait_ms = int(round((time.monotonic() - session_wait_started) * 1000))
            session_login_ms = 0
            command_credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else {}
            session_credentials = dict(command_credentials)
            session_credentials.pop("operation_password", None)
            expected_hash = hashlib.sha256(canonical_json(session_credentials)).hexdigest() if session_credentials else ""
            if not expected_hash:
                return self._execute_isolated_command(environment, payload, account_id, progress)

            with self.session_lock:
                session = self.sessions.get(subscription_id)

            now_epoch = time.time()
            session_stale = (
                not isinstance(session, dict)
                or session.get("client") is None
                or session.get("credential_hash") != expected_hash
                or (self.session_max_age_seconds > 0 and now_epoch - float(session.get("created_at") or 0) >= self.session_max_age_seconds)
                or (self.session_idle_seconds > 0 and now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds)
            )
            if session_stale:
                login_started = time.monotonic()
                self._close_session_locked(subscription_id)
                session = self._create_persistent_session_locked(
                    subscription_id,
                    environment,
                    account_id,
                    session_credentials,
                    "command",
                )
                session_login_ms = int(round((time.monotonic() - login_started) * 1000))

            session["last_used_at"] = now_epoch
            try:
                handle_started = time.monotonic()
                try:
                    with self._dispatch_timeout(session["client"]):
                        result = connector.handle_command(
                            payload,
                            progress=progress,
                            borrowed_client=session["client"],
                            borrowed_vehicles=session.get("vehicles") if isinstance(session.get("vehicles"), list) else None,
                        )
                finally:
                    handle_command_ms = int(round((time.monotonic() - handle_started) * 1000))
                # 1.12.92 — `handle_command()` já terminou aqui. Em sessão
                # reutilizada não ocorreu autenticação, portanto não há estado de
                # autenticação para "confirmar". A chamada antiga a
                # record_account_auth_success() adquiria a trava global duas vezes
                # (incluindo limpeza de cooldown) e, em campo, reteve o retorno
                # por 11–37s DEPOIS de o carro já receber o comando.
                post_dispatch_started = time.monotonic()
                session["last_used_at"] = time.time()
                result["session_retained_for_fast_confirmation"] = True
                post_dispatch_local_ms = int(round((time.monotonic() - post_dispatch_started) * 1000))
                # 1.12.93 — o comando já foi aceito pela nuvem. O arme da
                # confirmação é bookkeeping LOCAL e não pode reter a trava da
                # conta/sessão por 7–23s. Só enfileiramos uma cópia imutável; o
                # worker FIFO persiste supersessão/janela logo depois.
                arm_started = time.monotonic()
                try:
                    self._queue_command_confirmation_arm(subscription_id, payload, result)
                finally:
                    confirmation_arm_ms = int(round((time.monotonic() - arm_started) * 1000))
                # `confirmation_arm_ms` passa a medir somente o custo de ENFILEIRAR
                # no caminho crítico. A duração real do SQLite é registrada pelo
                # worker assíncrono e nunca entra em `remote_execute_ms`.
                phase = result.get("phase_latency_ms")
                if isinstance(phase, dict):
                    phase["session_wait_ms"] = session_wait_ms
                    phase["session_login_ms"] = session_login_ms
                    phase["engine_precheck_ms"] = engine_precheck_ms
                    # As três somam engine_precheck_ms e dizem qual delas gastou.
                    phase["auth_status_ms"] = auth_status_ms
                    phase["engine_lock_wait_ms"] = engine_lock_wait_ms
                    phase["subscription_read_ms"] = subscription_read_ms
                    phase["handle_command_ms"] = handle_command_ms
                    phase["post_dispatch_local_ms"] = post_dispatch_local_ms
                    phase["confirmation_arm_ms"] = confirmation_arm_ms
                return result
            except Exception as exc:
                session["last_used_at"] = time.time()
                if connector.is_command_certificate_session_error(exc):
                    # Cert/sync ou a verificação remota pré-envio recusaram o token
                    # antes de qualquer ação chegar ao veículo. A sessão compartilhada
                    # é descartada e o mesmo comando é tentado uma única vez em uma
                    # autenticação limpa. Erros de token após aceite nunca entram aqui.
                    LOG.warning(
                        "Sessão de %s expirou na verificação pré-envio; recriando uma única vez antes da ação.",
                        subscription_id,
                    )
                    self._close_session_locked(subscription_id)
                    if progress is not None:
                        try:
                            progress(
                                "reconnecting",
                                "A sessão expirou antes do envio. Criando uma conexão limpa e protegida.",
                                {"session_recovery": True},
                            )
                        except Exception:
                            pass
                    recovered_session = self._create_persistent_session_locked(
                        subscription_id,
                        environment,
                        account_id,
                        session_credentials,
                        "command_recovery",
                    )
                    try:
                        recovered = connector.handle_command(
                            payload,
                            progress=progress,
                            borrowed_client=recovered_session["client"],
                            borrowed_vehicles=None,
                        )
                    except Exception as recovered_exc:
                        recovered_session["last_used_at"] = time.time()
                        if connector.is_authentication_error(recovered_exc):
                            self._close_session_locked(subscription_id)
                        raise
                    recovered_session["last_used_at"] = time.time()
                    # A sessão de recuperação acabou de ser autenticada por
                    # _create_persistent_session_locked(), que já registrou o
                    # sucesso real do login. Não repetir bookkeeping após o
                    # dispatch aceito.
                    recovered["session_recovered"] = True
                    recovered["session_reused"] = True
                    recovered["session_retained_for_fast_confirmation"] = True
                    # Mesma regra da sessão normal: depois de uma ação aceita,
                    # nenhuma gravação local segura a sessão/comando.
                    self._queue_command_confirmation_arm(subscription_id, payload, recovered)
                    return recovered
                if isinstance(exc, connector.ConnectorLoginCooldownError):
                    self._set_account_login_cooldown(environment, account_id, exc.retry_after_seconds, str(exc))
                if connector.is_authentication_error(exc):
                    self._close_session_locked(subscription_id)
                raise

    @contextlib.contextmanager
    def _telemetry_request_timeout(self, client: Any):
        """Teto curto somente enquanto uma leitura automática possui a conta.

        O mesmo cliente é reaproveitado por comandos e telemetria. Alterar o
        timeout permanentemente faria o comando manual herdar um teto pequeno;
        por isso o valor é emprestado e restaurado no `finally`.
        """
        previous = getattr(client, "timeout", None)
        changed = False
        if isinstance(previous, (int, float)) and not isinstance(previous, bool):
            target = max(1.0, min(float(previous), float(self.telemetry_network_timeout_seconds)))
            if target < float(previous):
                client.timeout = target
                changed = True
        try:
            yield
        finally:
            if changed:
                try:
                    client.timeout = previous
                except Exception:
                    pass

    @contextlib.contextmanager
    def _dispatch_timeout(self, client: Any):
        """Empresta ao despacho um tempo limite maior, e devolve o da telemetria.

        1.12.71 — a 1.12.70 resolveu isto elevando o tempo limite do cliente
        inteiro, e isso tinha um custo escondido: o MESMO cliente é usado pela
        leitura de telemetria, que segura a trava da conta durante a chamada.
        Alongar a leitura alonga a espera de quem manda o comando seguinte — a
        causa 4 dos logs de 02/08/2026, em que um comando esperou 36s por uma
        trava do poller.

        A biblioteca lê `self.timeout` **na hora da chamada** (`client.py`, os
        quatro pontos de `timeout=self.timeout`), não na construção. Então dá
        para dar os segundos a mais só ao despacho: quem precisa deles é o
        despacho, e quem paga por eles seria a telemetria.

        Seguro contra concorrência porque todo este trecho roda dentro de
        `_session_operation_lock(subscription_id)`, e cada assinatura tem o seu
        cliente. Se a biblioteca instalada não expuser `timeout`, não faz nada:
        o despacho continua com o que houver, como antes.
        """
        previous = getattr(client, "timeout", None)
        raised = False
        if isinstance(previous, (int, float)) and not isinstance(previous, bool):
            target = max(int(previous), self.COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS)
            # O mesmo teto que `connector.create_client` aplica: emprestar mais
            # que isso deixaria o comando pendurado além do que a fila do
            # servidor tolera.
            target = min(target, 45)
            if target > previous:
                try:
                    client.timeout = target
                    raised = True
                except Exception:  # noqa: BLE001
                    raised = False
        try:
            yield
        finally:
            if raised:
                try:
                    client.timeout = previous
                except Exception:  # noqa: BLE001
                    pass

    def _queue_command_confirmation_arm(
        self,
        subscription_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> bool:
        """Queue local confirmation bookkeeping without delaying a sent command.

        Only immutable command metadata is copied. No Leapmotor client, session,
        credential, callback or physical-command function enters this queue.
        With one worker, jobs execute in the exact order in which accepted
        commands leave the protected dispatch path.
        """
        command = str(payload.get("command") or "").strip().lower()
        dispatched = bool(result.get("command_dispatched") or result.get("cloud_accepted"))
        if command not in TELEMETRY_CONFIRMABLE_COMMANDS or not dispatched:
            result["confirmation_arm_queued"] = False
            result["confirmation_arm_state"] = "not_required"
            result["confirmation_armed_by_gateway"] = False
            return False

        parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        payload_snapshot = {
            "command": command,
            "vehicle_id": str(payload.get("vehicle_id") or "").strip()[:190],
            "request_id": str(payload.get("request_id") or "").strip()[:96],
            # JSON round-trip prevents a mutable nested dict from changing after
            # the command result has already been returned to connector_server.
            "parameters": json.loads(json.dumps(parameters, ensure_ascii=False, default=connector.json_default)),
        }
        result_snapshot = {
            "command_dispatched": bool(result.get("command_dispatched")),
            "cloud_accepted": bool(result.get("cloud_accepted")),
            "confirmation_pending": bool(result.get("confirmation_pending")),
        }

        pool = getattr(self, "_confirmation_arm_pool", None)
        if pool is None:
            result["confirmation_arm_queued"] = False
            result["confirmation_arm_state"] = "site_recovery"
            result["confirmation_armed_by_gateway"] = False
            LOG.warning(
                "Comando %s foi aceito, mas o worker local de confirmação está encerrado; "
                "o boost do site fará a recuperação sem reenviar a ação física.",
                command,
            )
            return False

        try:
            pool.submit(
                self._arm_command_confirmation_background,
                subscription_id,
                payload_snapshot,
                result_snapshot,
            )
        except RuntimeError as exc:
            # Executor em shutdown: a ação física já aconteceu e jamais é
            # repetida por causa de falha local de bookkeeping.
            result["confirmation_arm_queued"] = False
            result["confirmation_arm_state"] = "site_recovery"
            result["confirmation_armed_by_gateway"] = False
            LOG.warning(
                "Comando %s foi aceito, mas o arme local não pôde ser enfileirado: %s. "
                "Nenhum reenvio físico será feito.",
                command,
                connector.clean_message(str(exc)),
            )
            return False

        result["confirmation_arm_queued"] = True
        result["confirmation_arm_state"] = "queued"
        # Compatibilidade: para uma confirmação pendente, o Gateway assumiu a
        # responsabilidade assim que o job FIFO foi aceito. O worker registra a
        # janela logo em seguida; o site continua tendo seu boost idempotente
        # como rede de segurança em caso de reinício do processo.
        result["confirmation_armed_by_gateway"] = bool(result.get("confirmation_pending"))
        result["confirmation_window_reused"] = False
        return True

    def _arm_command_confirmation_background(
        self,
        subscription_id: str,
        payload_snapshot: dict[str, Any],
        result_snapshot: dict[str, Any],
    ) -> None:
        """Persist one queued confirmation job; never dispatch a vehicle action."""
        started = time.monotonic()
        command = str(payload_snapshot.get("command") or "").strip().lower()
        request_id = str(payload_snapshot.get("request_id") or "").strip()[:96]
        local_result = dict(result_snapshot)
        try:
            self._arm_command_confirmation(subscription_id, payload_snapshot, local_result)
        except BaseException as exc:  # noqa: BLE001
            # Defesa final. `_arm_command_confirmation` já é best-effort, mas
            # nenhuma exceção desta thread pode autorizar retry físico.
            elapsed_ms = int(round((time.monotonic() - started) * 1000))
            LOG.warning(
                "Arme assíncrono de %s (%s) falhou em %sms: %s. "
                "A ação física não será repetida.",
                command or "desconhecido",
                request_id or "sem request_id",
                elapsed_ms,
                connector.clean_message(str(exc)),
            )
            return

        elapsed_ms = int(round((time.monotonic() - started) * 1000))
        armed = bool(local_result.get("confirmation_armed_by_gateway"))
        reused = bool(local_result.get("confirmation_window_reused"))
        pending = bool(result_snapshot.get("confirmation_pending"))
        if pending and not armed:
            LOG.warning(
                "Arme assíncrono de %s (%s) terminou em %sms sem janela local; "
                "o site poderá recuperar pelo boost idempotente.",
                command or "desconhecido",
                request_id or "sem request_id",
                elapsed_ms,
            )
        else:
            LOG.info(
                "Arme assíncrono de %s (%s) concluído em %sms; armada=%s reutilizada=%s.",
                command or "desconhecido",
                request_id or "sem request_id",
                elapsed_ms,
                armed,
                reused,
            )

    def _arm_command_confirmation(
        self,
        subscription_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        """Arm FAST telemetry before the site starts polling command status.

        The command worker already knows the exact subscription, remote vehicle
        and immutable request id. Persisting that context here removes the
        dependency on a later PHP worker round-trip. The site may repeat the
        boost as a recovery signal; ``boost`` preserves an active window for the
        same request instead of resetting its samples.
        """
        command = str(payload.get("command") or "").strip().lower()
        dispatched = bool(result.get("command_dispatched") or result.get("cloud_accepted"))
        pending = bool(result.get("confirmation_pending"))

        if command in TELEMETRY_CONFIRMABLE_COMMANDS and dispatched and not pending:
            supersede_started = time.monotonic()
            try:
                now_epoch = time.time()
                now_iso = utc_iso()
                with self.schedule_lock, self._db(timeout_seconds=2.0) as db:
                    self._supersede_pending_confirmations(
                        db,
                        subscription_id,
                        command,
                        str(payload.get("vehicle_id") or "").strip()[:190],
                        str(payload.get("request_id") or "").strip()[:96],
                        now_epoch,
                        now_iso,
                    )
            except Exception as exc:  # noqa: BLE001
                LOG.warning(
                    "Comando %s foi aceito, mas a limpeza da confirmação anterior em %s falhou: %s",
                    command, subscription_id, connector.clean_message(str(exc)),
                )
            finally:
                supersede_ms = int(round((time.monotonic() - supersede_started) * 1000))
                if supersede_ms >= TELEMETRY_STAGE_LOG_THRESHOLD_MS:
                    LOG.info(
                        "CONFIRM_ARM_DIAG command=%s stage=supersede ms=%s subscription=%s",
                        command, supersede_ms, subscription_id,
                    )

        if (
            command not in TELEMETRY_CONFIRMABLE_COMMANDS
            or not pending
            or not dispatched
        ):
            result["confirmation_armed_by_gateway"] = False
            return

        context = {
            "command_key": command,
            "command_id": 0,
            "vehicle_remote_id": str(payload.get("vehicle_id") or "").strip()[:190],
            "parameters": payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {},
            "request_id": str(payload.get("request_id") or "").strip()[:96],
        }
        try:
            boost_started = time.monotonic()
            armed = self.boost(
                subscription_id,
                seconds=180,
                profile="command",
                context=context,
            )
            boost_ms = int(round((time.monotonic() - boost_started) * 1000))
            if boost_ms >= TELEMETRY_STAGE_LOG_THRESHOLD_MS:
                LOG.info(
                    "CONFIRM_ARM_DIAG command=%s stage=boost ms=%s subscription=%s",
                    command, boost_ms, subscription_id,
                )
            result["confirmation_armed_by_gateway"] = bool(armed.get("ok"))
            result["confirmation_window_reused"] = bool(armed.get("confirmation_window_reused"))
            if not armed.get("ok"):
                LOG.warning(
                    "Comando %s foi aceito, mas a janela FAST interna de %s não pôde ser armada: %s",
                    command,
                    subscription_id,
                    connector.clean_message(str(armed.get("message") or "indisponível")),
                )
        except Exception as exc:  # noqa: BLE001
            # A ação física já foi aceita. Uma falha local ao armar a leitura
            # não transforma sucesso remoto em erro nem autoriza reenvio.
            result["confirmation_armed_by_gateway"] = False
            LOG.warning(
                "Comando %s foi aceito, mas a janela FAST interna de %s será recuperada pelo site: %s",
                command,
                subscription_id,
                connector.clean_message(str(exc)),
            )

    def invalidate_account_session(self, environment: str, payload: dict[str, Any]) -> int:
        """Feche a sessão automática antes de uma operação manual da conta.

        A nuvem pode rejeitar dois tokens simultâneos. O servidor chama este
        método somente depois de adquirir a trava exclusiva da conta.
        """
        try:
            account_id = int(payload.get("account_id") or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id < 1:
            return 0
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT subscription_id FROM subscriptions WHERE environment=? AND account_id=?",
                (str(environment or ""), account_id),
            ).fetchall()
        for row in rows:
            self._close_session(str(row["subscription_id"]))
        if rows:
            LOG.info("Sessão automática de %s conta(s) encerrada antes da operação manual para evitar conflito de token.", len(rows))
        return len(rows)

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        # O worker respeita next_run_at exatamente como foi persistido. Reiniciar
        # o App não antecipa cooldown nem espera progressiva.
        self._poll_pool = ThreadPoolExecutor(
            max_workers=self.poll_workers,
            thread_name_prefix="leaphub-telemetry-poll",
        )
        self.worker = threading.Thread(target=self._run, name="leaphub-telemetry", daemon=True)
        self.worker.start()
        self.maintenance_worker = threading.Thread(
            target=self._run_maintenance, name="leaphub-telemetry-maintenance", daemon=True
        )
        self.maintenance_worker.start()
        self.delivery_worker = threading.Thread(
            target=self._run_delivery, name="leaphub-telemetry-delivery", daemon=True
        )
        self.delivery_worker.start()
        LOG.info(
            "Telemetria contínua iniciada com fila persistente em %s; %s coletas paralelas e entrega dedicada.",
            self.db_path,
            self.poll_workers,
        )

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        self.delivery_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=12)
        if self.delivery_worker and self.delivery_worker.is_alive():
            self.delivery_worker.join(timeout=12)
        if self.maintenance_worker and self.maintenance_worker.is_alive():
            self.maintenance_worker.join(timeout=6)
        pool, self._poll_pool = self._poll_pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        # 1.12.93 — jobs de confirmação são locais e pequenos, mas podem estar
        # aguardando self.lock/SQLite. Não cancelar: preservar FIFO/supersessão
        # e terminar o bookkeeping aceito antes de fechar o storage.
        confirmation_pool, self._confirmation_arm_pool = self._confirmation_arm_pool, None
        if confirmation_pool is not None:
            confirmation_pool.shutdown(wait=True, cancel_futures=False)
        # Pollers já pararam, então nenhum render novo pode nascer. O worker
        # visual é local e termina antes do SQLite ser fechado.
        visual_pool, self._visual_render_pool = self._visual_render_pool, None
        if visual_pool is not None:
            visual_pool.shutdown(wait=True, cancel_futures=False)
        self._close_all_sessions()
        self.close_storage()
        self._close_delivery_connection()

    def upsert(self, environment: str, payload: dict[str, Any]) -> dict[str, Any]:
        subscription_id = str(payload.get("subscription_id") or "").strip()[:190]
        account_id = int(payload.get("account_id") or 0)
        credentials = payload.get("credentials")
        ids = payload.get("vehicle_ids")
        enabled = bool(payload.get("enabled", True))
        credentials_verified = bool(payload.get("credentials_verified", False))
        if not subscription_id or account_id < 1 or not isinstance(credentials, dict) or not isinstance(ids, list):
            raise ValueError("Assinatura de telemetria incompleta.")
        if environment not in self.secrets or len(self.secrets[environment]) < 32:
            raise ValueError("Ambiente sem chave válida.")
        vehicle_ids = sorted({str(item).strip()[:190] for item in ids if str(item).strip()})
        if not vehicle_ids:
            raise ValueError("Nenhum veículo informado para a assinatura.")
        for key in ("email", "password", "certificate_pem", "private_key_pem"):
            if not str(credentials.get(key) or "").strip():
                raise ValueError("Credenciais de telemetria incompletas.")

        now = utc_iso()
        now_epoch = time.time()
        credential_hash = hashlib.sha256(canonical_json(credentials)).hexdigest()
        config_hash = hashlib.sha256(canonical_json({
            "environment": environment,
            "account_id": account_id,
            "vehicle_ids": vehicle_ids,
            "enabled": enabled,
            "credential_hash": credential_hash,
        })).hexdigest()
        with self.lock, self._db() as db:
            existing = db.execute(
                "SELECT credential_hash, config_hash, credentials_encrypted, auth_required, cooldown_until, cooldown_reason, active_until, interactive_until, command_until, next_run_at, status, enabled "
                "FROM subscriptions WHERE subscription_id=? LIMIT 1",
                (subscription_id,),
            ).fetchone()

        previous_hash = str(existing["credential_hash"] or "") if existing is not None else ""
        if existing is not None and not previous_hash:
            # Primeira execução após atualizar uma base antiga: calcula o hash
            # das credenciais já armazenadas para não apagar cooldown ou bloqueio
            # de autenticação apenas porque a coluna ainda estava vazia.
            try:
                previous_payload = self.fernet.decrypt(bytes(existing["credentials_encrypted"]))
                previous_hash = hashlib.sha256(previous_payload).hexdigest()
            except (InvalidToken, ValueError, TypeError):
                previous_hash = ""
        credentials_changed = existing is None or not previous_hash or not hmac.compare_digest(previous_hash, credential_hash)
        existing_auth_required = bool(existing is not None and int(existing["auth_required"] or 0) == 1)
        existing_cooldown_until = float(existing["cooldown_until"] or 0) if existing is not None else 0.0
        protected_auth = enabled and existing_auth_required and not credentials_changed and not credentials_verified
        protected_cooldown = enabled and existing_cooldown_until > now_epoch and not credentials_changed and not credentials_verified
        existing_config_hash = str(existing["config_hash"] or "") if existing is not None else ""
        session_present = existing is not None and self._has_session(subscription_id)
        verified_healthy_session = credentials_verified and not credentials_changed and session_present
        if (
            existing is not None
            and existing_config_hash
            and hmac.compare_digest(existing_config_hash, config_hash)
            and (not credentials_verified or verified_healthy_session)
        ):
            status = str(existing["status"] or "waiting")
            response = {
                "ok": not protected_auth and not protected_cooldown,
                "subscription_id": subscription_id,
                "vehicle_count": len(vehicle_ids),
                "unchanged": True,
                "deduplicated": True,
                "credentials_changed": False,
                "credentials_verified": credentials_verified,
                "auth_reset": False,
                "cooldown_reset": False,
                "session_preserved": session_present,
                "next_run_seconds": max(0, int(float(existing["next_run_at"] or 0) - now_epoch)),
                "status": status,
            }
            ORCHESTRATOR.record_deduplicated("telemetry_subscription_upsert")
            if protected_auth:
                response.update({"auth_required": True, "protected": True, "message": "Credenciais recusadas anteriormente; confirme a conta antes de uma nova tentativa."})
            elif protected_cooldown:
                response.update({
                    "cooldown": True,
                    "protected": True,
                    "retry_after_seconds": max(1, int(existing_cooldown_until - now_epoch)),
                    "cooldown_reason": str(existing["cooldown_reason"] or "login"),
                    "message": "A Leapmotor ainda não liberou novas chamadas. O Gateway aguardará automaticamente.",
                })
            return response

        # Reenvios comuns com as mesmas credenciais preservam a proteção. O site
        # pode enviar credentials_verified somente depois de uma consulta manual
        # bem-sucedida à nuvem. Essa confirmação assinada elimina o bloqueio preso
        # sem exigir que o usuário altere e salve a mesma senha novamente.
        if protected_auth:
            status = "auth_required"
            active_until = 0.0
            interactive_until = 0.0
            command_until = 0.0
            next_run = now_epoch + 86400
            auth_required = 1
            cooldown_until = 0.0
        elif protected_cooldown:
            status = "cooldown"
            active_until = 0.0
            interactive_until = 0.0
            command_until = 0.0
            next_run = existing_cooldown_until
            auth_required = 0
            cooldown_until = existing_cooldown_until
        elif not enabled:
            status = "disabled"
            active_until = 0.0
            interactive_until = 0.0
            command_until = 0.0
            next_run = now_epoch + self.sleep_seconds
            auth_required = 0
            cooldown_until = 0.0
        else:
            status = "waiting"
            previous_active = float(existing["active_until"] or 0) if existing is not None else 0.0
            active_until = max(previous_active, now_epoch + self.presence_window_seconds)
            previous_interactive = float(existing["interactive_until"] or 0) if existing is not None and not credentials_changed else 0.0
            interactive_until = max(0.0, previous_interactive)
            previous_command = float(existing["command_until"] or 0) if existing is not None and not credentials_changed else 0.0
            command_until = max(0.0, previous_command)
            previous_next = float(existing["next_run_at"] or 0) if existing is not None else 0.0
            next_run = min(previous_next, now_epoch + 1.0) if previous_next > now_epoch else now_epoch + random.uniform(0.5, 1.5)
            auth_required = 0
            cooldown_until = 0.0

        # `credentials_verified` confirma que uma consulta manual funcionou,
        # mas não significa que a sessão ativa ficou inválida. Fechá-la aqui
        # aguardava a operação de telemetria em curso e fazia o site repetir o
        # mesmo upsert após o timeout. Somente uma verificação sem sessão ativa
        # precisa limpar o estado de recuperação e preparar uma nova sessão.
        verification_requires_reset = credentials_verified and not verified_healthy_session
        if credentials_changed or verification_requires_reset or not enabled:
            self._close_session(subscription_id)
        encrypted = self.fernet.encrypt(canonical_json(credentials))
        with self.lock, self._db() as db:
            db.execute(
                """
                INSERT INTO subscriptions
                (subscription_id, environment, account_id, credentials_encrypted, vehicle_ids_json, enabled, status, next_run_at,
                 last_run_at, last_success_at, last_delivery_at, last_error, last_state, parked_streak, consecutive_failures,
                 cooldown_until, active_until, interactive_until, command_until, last_presence_at, auth_required, credential_hash, config_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscription_id) DO UPDATE SET
                    environment=excluded.environment, account_id=excluded.account_id,
                    credentials_encrypted=excluded.credentials_encrypted, vehicle_ids_json=excluded.vehicle_ids_json,
                    enabled=excluded.enabled, status=excluded.status, next_run_at=excluded.next_run_at,
                    last_error=CASE WHEN excluded.status IN ('auth_required','cooldown') THEN subscriptions.last_error ELSE NULL END,
                    consecutive_failures=CASE WHEN excluded.status IN ('auth_required','cooldown') THEN subscriptions.consecutive_failures ELSE 0 END,
                    cooldown_until=excluded.cooldown_until, active_until=excluded.active_until,
                    interactive_until=excluded.interactive_until,
                    command_until=excluded.command_until,
                    last_presence_at=excluded.last_presence_at, auth_required=excluded.auth_required,
                    credential_hash=excluded.credential_hash, config_hash=excluded.config_hash, updated_at=excluded.updated_at
                """,
                (subscription_id, environment, account_id, encrypted, json.dumps(vehicle_ids), 1 if enabled else 0,
                 status, next_run, cooldown_until, active_until, interactive_until, command_until, now, auth_required, credential_hash, config_hash, now, now),
            )

        self.wake_event.set()
        if protected_auth:
            return {
                "ok": False,
                "subscription_id": subscription_id,
                "auth_required": True,
                "protected": True,
                "credentials_changed": False,
                "message": "Credenciais recusadas anteriormente; confirme a conta antes de uma nova tentativa.",
            }
        if protected_cooldown:
            return {
                "ok": False,
                "subscription_id": subscription_id,
                "cooldown": True,
                "protected": True,
                "credentials_changed": False,
                "retry_after_seconds": max(1, int(existing_cooldown_until - now_epoch)),
                "cooldown_reason": str(existing["cooldown_reason"] or "rate_limit") if existing is not None else "rate_limit",
                "message": (
                    "A Leapmotor ainda não liberou uma nova autenticação. O Gateway aguardará automaticamente."
                    if existing is not None and str(existing["cooldown_reason"] or "") == "login"
                    else "Proteção contra limite de requisições ainda está ativa."
                ),
            }
        return {
            "ok": True,
            "subscription_id": subscription_id,
            "vehicle_count": len(vehicle_ids),
            "active_seconds": max(0, int(active_until - time.time())),
            "next_run_seconds": int(max(0, next_run - time.time())),
            "credentials_changed": credentials_changed,
            "credentials_verified": credentials_verified,
            "auth_reset": credentials_verified and existing_auth_required,
            "cooldown_reset": credentials_verified and existing_cooldown_until > now_epoch,
            "session_preserved": not credentials_changed and not verification_requires_reset and self._has_session(subscription_id),
        }

    def remove(self, subscription_id: str) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        if not subscription_id:
            raise ValueError("Identificador da assinatura ausente.")
        self._close_session(subscription_id)
        with self.lock, self._db() as db:
            cursor = db.execute(
                "UPDATE subscriptions SET enabled=0, status='disabled', active_until=0, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, updated_at=? WHERE subscription_id=?",
                (utc_iso(), subscription_id),
            )
        self.wake_event.set()
        return {"ok": True, "subscription_id": subscription_id, "disabled": cursor.rowcount > 0}

    def release_interactive(self, subscription_id: str) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        if not subscription_id:
            raise ValueError("Identificador da assinatura ausente.")
        now_epoch = time.time()
        now_iso = utc_iso()
        with self.lock, self._db() as db:
            row = db.execute(
                "SELECT enabled, status, next_run_at, command_until FROM subscriptions WHERE subscription_id=? LIMIT 1",
                (subscription_id,),
            ).fetchone()
            if row is None:
                return {"ok": True, "subscription_id": subscription_id, "released": False}
            status = str(row["status"] or "")
            next_run = float(row["next_run_at"] or 0)
            command_active = float(row["command_until"] or 0) > now_epoch
            # Fechar a aba remove somente a janela interativa normal. Uma janela
            # de confirmação criada por comando remoto continua ativa para que o
            # carro possa acordar e o novo estado chegue mesmo sem a tela aberta.
            if command_active:
                if status not in {"auth_required", "cooldown", "recovering", "error"}:
                    status = "waiting"
                    next_run = min(next_run, now_epoch + 0.5) if next_run > now_epoch else now_epoch + 0.5
            elif status not in {"auth_required", "cooldown", "recovering", "error"}:
                if self.background_enabled:
                    status = "background"
                    # Não adia uma leitura já próxima e nunca deixa o próximo
                    # teste de atividade além do limite econômico configurado.
                    next_run = min(max(next_run, now_epoch + 5), now_epoch + self.background_seconds)
                else:
                    status = "idle"
                    next_run = max(next_run, now_epoch + self.sleep_seconds)
            cursor = db.execute(
                "UPDATE subscriptions SET status=?,interactive_until=0,next_run_at=?,updated_at=? WHERE subscription_id=?",
                (status, next_run, now_iso, subscription_id),
            )
        self.wake_event.set()
        return {
            "ok": True,
            "subscription_id": subscription_id,
            "released": cursor.rowcount > 0,
            "command_window_preserved": command_active,
            "session_preserved": self._has_session(subscription_id),
        }

    # ------------------------------------------------------------------
    # 1.12.62 — confirmações pendentes, uma por comando
    #
    # A janela de confirmação era uma só por assinatura, guardada em colunas
    # da própria linha (`command_key`, `command_context_json`, ...). Dois
    # comandos seguidos com chaves diferentes disputavam esse espaço: o
    # segundo sobrescrevia o contexto do primeiro, e o primeiro nunca recebia
    # veredito — nem confirmado, nem inconclusivo. Foi o que aconteceu em
    # campo em 30/07/2026 com `sunshade_open` seguido de `unlock`.
    #
    # As colunas antigas continuam preenchidas com a espera mais recente,
    # porque o painel e o diagnóstico as leem; a fonte da verdade passa a ser
    # a tabela.
    # ------------------------------------------------------------------
    CONFIRMATION_RETENTION_SECONDS = 3600

    @staticmethod
    def _confirmation_id(subscription_id: str, command_key: str, vehicle_id: str, request_id: str) -> str:
        base = str(request_id or "").strip()
        if not base:
            # Sem request_id resta o par comando+veículo para distinguir duas
            # esperas — o mesmo critério que a versão anterior usava.
            base = "auto:{}:{}".format(command_key, vehicle_id)
        return "{}|{}".format(subscription_id, base)

    def _match_pending_confirmation(
        self,
        db: sqlite3.Connection,
        subscription_id: str,
        command_key: str,
        vehicle_id: str,
        request_id: str,
        now_epoch: float,
    ) -> sqlite3.Row | None:
        """Espera ativa que este boost deve estender em vez de duplicar.

        O site repete o boost como sinal de recuperação. Reaproveitar a espera
        preserva as amostras já contadas; criar outra reiniciaria a contagem a
        cada repetição e a confirmação nunca terminaria.

        1.12.70 — o casamento passou a ser simétrico. Antes, um boost SEM
        request_id adotava a espera existente, mas um boost COM request_id
        nunca adotava uma espera sem id: criava a sua própria, e o mesmo comando
        físico ficava com DUAS esperas pendentes. A gêmea sem id confirma
        sozinha (o estado dela já está satisfeito quando ela nasce) e escreve no
        log "confirmado ... 1 comando(s) ainda aguardam", que se lê como se o
        comando recém-enviado tivesse sido o confirmado. Foi o que apareceu duas
        vezes em campo em 02/08/2026, às 13:43:23 e às 14:03:43.
        """
        rows = db.execute(
            "SELECT * FROM command_confirmations WHERE subscription_id=? AND status='pending' AND expires_at>? "
            "ORDER BY started_at DESC",
            (subscription_id, now_epoch),
        ).fetchall()
        anonymous: sqlite3.Row | None = None
        for row in rows:
            if str(row["command_key"] or "") != command_key:
                continue
            if str(row["command_vehicle_id"] or "") != vehicle_id:
                continue
            existing_request = str(row["request_id"] or "")
            # Boost sem request_id adota a espera existente; id igual é o mesmo
            # comando repetido pelo site como recuperação.
            if not request_id or request_id == existing_request:
                return row
            # Espera sem id nenhum, e agora chegou um id para a mesma dupla
            # comando+veículo: é o MESMO comando, armado por quem ainda não
            # conhecia o id. Adotar, e batizar. Uma espera com id DIFERENTE
            # continua sendo outro comando e merece a sua própria.
            if not existing_request and anonymous is None:
                anonymous = row
        return anonymous

    def _settled_confirmation(
        self,
        db: sqlite3.Connection,
        subscription_id: str,
        command_key: str,
        vehicle_id: str,
        now_epoch: float,
        window_seconds: int,
        request_id: str = "",
    ) -> sqlite3.Row | None:
        """Veredito recente do MESMO comando, para um boost repetido.

        1.12.74 — `_adopt_legacy_confirmation` já se protege disto desde a
        1.12.70 (a guarda logo acima do INSERT dela), mas o `boost` não se
        protegia, e é por ele que a repetição chega.

        O site repete o boost depois do comando como sinal de recuperação.
        Quando ele chega SEM `request_id` e a espera nomeada — armada pelo
        próprio Gateway no despacho, com o id do comando — já confirmou, não há
        nada pendente para adotar: nasce uma gêmea. Ela confirma na primeira
        leitura, porque o estado que procura já foi atingido, e enquanto vive
        mantém a assinatura em cadência de comando, gastando leituras da nuvem e
        trava de conta de que o comando SEGUINTE precisa.

        Medido em campo em 11/08/2026: `unlock (ref_…)` confirmado às 13:14:29 e
        `unlock (sem request_id)` às 13:14:37; a gêmea do `sunshade_open` das
        13:16:11 nasceu às 13:17:21 e gastou 8 leituras/111s procurando a
        cortina aberta enquanto ela era fechada.

        Só vale para veredito POSITIVO. Uma janela que se esgotou sem concluir
        merece ser rearmada — ali o boost do site é recuperação de verdade, e
        recusá-la deixaria o comando sem veredito.
        """
        # 1.12.75 — quando o boost traz `request_id`, a busca é POR ELE. A
        # 1.12.74 só cobria o caso anônimo porque, na época, o site descartava o
        # id (consertado na 1.12.331 do site). Com o id de volta, o caso comum
        # passou a ser o IDENTIFICADO — e ele atravessava esta guarda, caía no
        # `INSERT OR REPLACE` do `_register_confirmation` e RESSUSCITAVA a linha
        # já confirmada com `started_at` novo. Medido em campo em 12/08/2026:
        # cinco dos seis comandos confirmaram DUAS vezes com o mesmo `ref_`, a
        # segunda com "1 leitura e 0s", ~45s depois — a cadência do boost da tela.
        #
        # Com identidade exata isto é seguro: um toque NOVO no botão gera um
        # `request_uuid` novo, logo um `confirmation_id` novo, e não é suprimido.
        parametros: list[Any] = [subscription_id, command_key, vehicle_id]
        if request_id:
            parametros.append(request_id)
        parametros.append(now_epoch - max(1, int(window_seconds)))
        return db.execute(
            "SELECT * FROM command_confirmations WHERE subscription_id=? AND command_key=? "
            "AND IFNULL(command_vehicle_id,'')=?"
            + (" AND request_id=?" if request_id else "")
            + " AND status='confirmed' AND resolved_at>=? ORDER BY resolved_at DESC LIMIT 1",
            tuple(parametros),
        ).fetchone()

    def _supersede_pending_confirmations(
        self,
        db: sqlite3.Connection,
        subscription_id: str,
        command_key: str,
        vehicle_id: str,
        request_id: str,
        now_epoch: float,
        now_iso: str,
    ) -> int:
        """Encerra esperas antigas que a nova intenção tornou impossíveis.

        Só atua dentro da mesma família e no mesmo veículo. Repetição do mesmo
        request/comando continua sendo adotada por `_match_pending_confirmation`.
        """
        family = CONFIRMATION_SUPERSESSION_GROUP.get(command_key)
        if not family:
            return 0
        commands = CONFIRMATION_SUPERSESSION_FAMILIES.get(family, frozenset())
        include_same_intent = command_key in {"sunshade_position", "windshield_defrost"} and bool(request_id)
        opposites = sorted(
            item for item in commands if item != command_key or include_same_intent
        )
        if not opposites:
            return 0
        placeholders = ",".join("?" for _ in opposites)
        same_request_guard = (
            " AND NOT (command_key=? AND IFNULL(request_id,'')=?)"
            if include_same_intent else ""
        )
        sql = (
            "UPDATE command_confirmations SET status='superseded',resolution=?,resolved_at=?,updated_at=? "
            "WHERE subscription_id=? AND IFNULL(command_vehicle_id,'')=? AND status='pending' "
            f"AND command_key IN ({placeholders})" + same_request_guard
        )
        params: list[Any] = [
            f"superseded_by:{command_key}",
            now_epoch,
            now_iso,
            subscription_id,
            vehicle_id,
            *opposites,
        ]
        if include_same_intent:
            params.extend([command_key, request_id])
        cursor = db.execute(sql, tuple(params))
        count = max(0, int(cursor.rowcount or 0))
        if count:
            LOG.info(
                "%s confirmação(ões) antiga(s) de %s foram supersedidas por %s em %s.",
                count, family, command_key, subscription_id,
            )
        return count

    def _register_confirmation(
        self,
        db: sqlite3.Connection,
        subscription_id: str,
        command_key: str,
        vehicle_id: str,
        request_id: str,
        context_json: str,
        seconds: int,
        now_epoch: float,
        now_iso: str,
    ) -> tuple[str, bool]:
        self._supersede_pending_confirmations(
            db, subscription_id, command_key, vehicle_id, request_id, now_epoch, now_iso
        )
        existing = self._match_pending_confirmation(
            db, subscription_id, command_key, vehicle_id, request_id, now_epoch
        )
        if existing is not None:
            adopted = str(existing["confirmation_id"])
            # O `confirmation_id` é chave primária e não muda; o que muda é a
            # identidade gravada na linha. Batizar a espera anônima é o que
            # impede a próxima repetição do boost de criar a gêmea de novo.
            if request_id and not str(existing["request_id"] or ""):
                db.execute(
                    "UPDATE command_confirmations SET request_id=?,expires_at=MAX(expires_at,?),"
                    "context_json=?,updated_at=? WHERE confirmation_id=?",
                    (request_id, now_epoch + seconds, context_json, now_iso, adopted),
                )
            else:
                db.execute(
                    "UPDATE command_confirmations SET expires_at=MAX(expires_at,?),context_json=?,updated_at=? "
                    "WHERE confirmation_id=?",
                    (now_epoch + seconds, context_json, now_iso, adopted),
                )
            return adopted, True
        settled = self._settled_confirmation(
            db, subscription_id, command_key, vehicle_id, now_epoch, seconds, request_id
        )
        if settled is not None:
            # Nada a rearmar e nada a mexer na linha: ela já tem veredito.
            # Devolver `True` faz o `boost` tomar o ramo de janela reusada, que
            # não zera `command_poll_count` nem reescreve o contexto do comando
            # na assinatura.
            return str(settled["confirmation_id"] or ""), True
        confirmation_id = self._confirmation_id(subscription_id, command_key, vehicle_id, request_id)
        db.execute(
            "INSERT OR REPLACE INTO command_confirmations "
            "(confirmation_id,subscription_id,request_id,command_key,command_vehicle_id,context_json,"
            "started_at,expires_at,poll_count,evaluated_samples,stale_samples,status,resolution,resolved_at,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,0,0,0,'pending',NULL,0,?,?)",
            (
                confirmation_id,
                subscription_id,
                request_id,
                command_key,
                vehicle_id or None,
                context_json,
                now_epoch,
                now_epoch + seconds,
                now_iso,
                now_iso,
            ),
        )
        return confirmation_id, False

    @staticmethod
    def _pending_confirmations(
        db: sqlite3.Connection, subscription_id: str
    ) -> list[sqlite3.Row]:
        return list(
            db.execute(
                "SELECT * FROM command_confirmations WHERE subscription_id=? AND status='pending' "
                "ORDER BY started_at ASC",
                (subscription_id,),
            ).fetchall()
        )

    # Folga antes de declarar vencida uma espera que ninguém mais visitou. Só
    # existe para não competir com um ciclo em andamento na mesma assinatura.
    CONFIRMATION_EXPIRY_GRACE_SECONDS = 60

    def _prune_confirmations(self, db: sqlite3.Connection, now_epoch: float) -> int:
        """Fecha esperas abandonadas e recolhe as já resolvidas.

        Caminhos como `release_interactive` e `_mark_auth_required` zeram as
        colunas de comando da assinatura; sem esta varredura a linha pendente
        correspondente sobreviveria a todos os ciclos seguintes, e um comando
        antigo continuaria consumindo leituras de um veredito que ninguém mais
        espera.
        """
        expired = db.execute(
            "UPDATE command_confirmations SET status='expired',resolution='window_abandoned',resolved_at=?,updated_at=? "
            "WHERE status='pending' AND expires_at>0 AND expires_at<?",
            (now_epoch, utc_iso(), now_epoch - self.CONFIRMATION_EXPIRY_GRACE_SECONDS),
        ).rowcount
        db.execute(
            "DELETE FROM command_confirmations WHERE status<>'pending' AND resolved_at>0 AND resolved_at<?",
            (now_epoch - self.CONFIRMATION_RETENTION_SECONDS,),
        )
        return max(0, int(expired or 0))

    def _adopt_legacy_confirmation(
        self, db: sqlite3.Connection, subscription: sqlite3.Row, now_epoch: float
    ) -> None:
        """Adota a janela que a versão anterior guardava na linha da assinatura.

        Um comando em voo no instante da atualização do Gateway não tem linha na
        tabela nova. Sem isto ele ficaria sem veredito justamente na versão que
        existe para acabar com veredito perdido.
        """
        sid = str(subscription["subscription_id"] or "")
        command_key = str(subscription["command_key"] or "").strip()
        if not sid or not command_key:
            return
        if float(subscription["command_until"] or 0) <= now_epoch:
            return
        existing = db.execute(
            "SELECT 1 FROM command_confirmations WHERE subscription_id=? AND status='pending' LIMIT 1",
            (sid,),
        ).fetchone()
        if existing is not None:
            return
        context_json = str(subscription["command_context_json"] or "{}")
        try:
            parsed = json.loads(context_json)
            request_id = str(parsed.get("request_id") or "") if isinstance(parsed, dict) else ""
        except (TypeError, ValueError, json.JSONDecodeError):
            request_id = ""
        vehicle_id = str(subscription["command_vehicle_id"] or "")
        started_at = float(subscription["command_started_at"] or 0) or now_epoch
        # 1.12.70 — as colunas da assinatura sobrevivem ao veredito quando outra
        # espera ainda estava pendente no ciclo que as leu. Sem esta guarda, o
        # ciclo seguinte relia as mesmas colunas e RESSUSCITAVA um comando já
        # confirmado como uma espera nova, sem id — a entrada fantasma que
        # confirma na primeira leitura, porque o estado dela já foi atingido, e
        # rouba a leitura do comando que acabou de ser despachado.
        resolved = db.execute(
            "SELECT 1 FROM command_confirmations WHERE subscription_id=? AND command_key=? "
            "AND status<>'pending' AND resolved_at>=? LIMIT 1",
            (sid, command_key, started_at),
        ).fetchone()
        if resolved is not None:
            return
        now_iso = utc_iso()
        db.execute(
            "INSERT OR IGNORE INTO command_confirmations "
            "(confirmation_id,subscription_id,request_id,command_key,command_vehicle_id,context_json,"
            "started_at,expires_at,poll_count,evaluated_samples,stale_samples,status,resolution,resolved_at,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,0,0,'pending',NULL,0,?,?)",
            (
                self._confirmation_id(sid, command_key, vehicle_id, request_id),
                sid,
                request_id,
                command_key,
                vehicle_id or None,
                context_json,
                started_at,
                float(subscription["command_until"] or 0),
                int(subscription["command_poll_count"] or 0),
                now_iso,
                now_iso,
            ),
        )
        LOG.info(
            "Confirmação de %s em %s foi adotada da versão anterior do Gateway; a janela continua de onde parou.",
            command_key,
            sid,
        )

    def _evaluate_confirmation(
        self, entry: sqlite3.Row, vehicles: list[dict[str, Any]], now_epoch: float
    ) -> dict[str, Any]:
        """Confronta esta leitura com uma espera. Não toca no banco."""
        command_key = str(entry["command_key"] or "")
        command_vehicle_id = str(entry["command_vehicle_id"] or "")
        started_at = float(entry["started_at"] or 0)
        expires_at = float(entry["expires_at"] or 0)
        try:
            parsed = json.loads(str(entry["context_json"] or "{}"))
            context = parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            context = {}

        confirmed = False
        evaluable = False
        target_seen = False
        # 1.12.56 — três causas distintas produzem o mesmo "sem confirmação
        # conclusiva": o veículo-alvo não apareceu, as amostras foram velhas
        # demais, ou o campo que o matcher consulta não veio.
        stale_samples = 0
        evaluated_samples = 0
        field_gaps: list[str] = []
        available_keys: list[str] = []
        # 1.12.60 — atraso da amostra em relação ao envio do comando. Separa
        # "o carro recebeu e não obedeceu" de "o carro não subiu nada novo".
        sample_lag: float | None = None
        for vehicle in vehicles:
            if command_vehicle_id and str(vehicle.get("remote_id") or "") != command_vehicle_id:
                continue
            target_seen = True
            telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
            # As chaves observadas são registradas para qualquer amostra, não só
            # para a que sobrevive ao teste de frescura: senão o log sai
            # "chaves=[nenhuma]", que se lê como telemetria vazia quando o caso
            # era só atraso.
            if telemetry:
                available_keys = sorted(str(key) for key in telemetry.keys())[:40]
            lag = self._command_sample_lag(telemetry, started_at)
            if lag is not None and (sample_lag is None or lag < sample_lag):
                sample_lag = lag
            if not self._command_sample_is_fresh(telemetry, started_at):
                stale_samples += 1
                continue
            evaluated_samples += 1
            matched, sample_evaluable = self._command_confirmation(command_key, telemetry, context)
            evaluable = evaluable or sample_evaluable
            if not sample_evaluable:
                # Guarda a última amostra inconclusiva; só nomes de campo.
                field_gaps = self._command_confirmation_gaps(command_key, telemetry)
                available_keys = sorted(str(key) for key in telemetry.keys())[:40]
            if matched:
                confirmed = True
                break

        poll_count = int(entry["poll_count"] or 0) + 1
        elapsed = max(0.0, now_epoch - started_at) if started_at > 0 else 0.0
        # 1.12.62 — quem encerra a espera é o PRAZO da janela; a contagem de
        # leituras é só teto de segurança contra cadência curta demais. Com o
        # critério antigo, cinco leituras esgotavam a janela em ~110s e um carro
        # que acabara de acordar era declarado inconclusivo com quase um minuto
        # de janela ainda disponível.
        reason = ""
        if not confirmed:
            if expires_at > 0 and now_epoch >= expires_at:
                reason = "window_deadline"
            elif poll_count >= self.command_max_polls:
                reason = "poll_budget"
        return {
            "confirmation_id": str(entry["confirmation_id"] or ""),
            "command_key": command_key,
            "command_vehicle_id": command_vehicle_id,
            "request_id": str(entry["request_id"] or ""),
            "confirmed": confirmed,
            "evaluable": evaluable,
            "exhausted": bool(reason),
            "reason": reason,
            "target_seen": target_seen,
            "evaluated_samples": evaluated_samples,
            "stale_samples": stale_samples,
            "field_gaps": field_gaps,
            "available_keys": available_keys,
            "sample_lag": sample_lag,
            "poll_count": poll_count,
            "elapsed": elapsed,
        }

    @staticmethod
    def _persist_confirmation(
        db: sqlite3.Connection, item: dict[str, Any], now_epoch: float, now_iso: str
    ) -> None:
        if item["confirmed"]:
            status, resolution = "confirmed", "telemetry_match"
        elif item["exhausted"]:
            status, resolution = "exhausted", str(item["reason"] or "exhausted")
        else:
            status, resolution = "pending", None
        db.execute(
            "UPDATE command_confirmations SET poll_count=?,evaluated_samples=evaluated_samples+?,"
            "stale_samples=stale_samples+?,status=?,resolution=?,resolved_at=?,updated_at=? "
            "WHERE confirmation_id=?",
            (
                int(item["poll_count"]),
                int(item["evaluated_samples"]),
                int(item["stale_samples"]),
                status,
                resolution,
                now_epoch if status != "pending" else 0.0,
                now_iso,
                str(item["confirmation_id"]),
            ),
        )

    def boost(
        self,
        subscription_id: str,
        seconds: int = 900,
        profile: str = "background",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        subscription_id = str(subscription_id or "").strip()[:190]
        requested_profile = str(profile or "").strip().lower()
        context = context if isinstance(context, dict) else {}
        command_key = str(context.get("command_key") or "").strip()[:80]
        command_vehicle_id = str(context.get("vehicle_remote_id") or "").strip()[:190]
        safe_context = {
            "command_id": int(context.get("command_id") or 0),
            "parameters": context.get("parameters") if isinstance(context.get("parameters"), dict) else {},
            "request_id": str(context.get("request_id") or "")[:96],
        }
        command_context_json = json.dumps(safe_context, ensure_ascii=False, separators=(",", ":"))[:4000]
        profile = requested_profile if requested_profile in {"background", "interactive", "command"} else "background"
        if profile == "command":
            seconds = max(30, min(180, int(seconds)))
        elif profile == "interactive":
            seconds = max(60, min(3600, int(seconds)))
        else:
            seconds = max(300, min(3600, int(seconds)))
        now_epoch = time.time()
        now_iso = utc_iso()
        schedule_wait_started = time.monotonic()
        with self.schedule_lock:
            schedule_wait_ms = int(round((time.monotonic() - schedule_wait_started) * 1000))
            if schedule_wait_ms >= TELEMETRY_STAGE_LOG_THRESHOLD_MS:
                LOG.info(
                    "CONFIRM_SCHED_DIAG stage=schedule_lock wait_ms=%s subscription=%s profile=%s",
                    schedule_wait_ms, subscription_id, profile,
                )
            with self._db(timeout_seconds=2.0) as db:
                row = db.execute(
                    "SELECT auth_required, cooldown_until, cooldown_reason, enabled, next_run_at, status,"
                    "command_until,command_key,command_vehicle_id,command_context_json,command_poll_count,command_started_at "
                    "FROM subscriptions WHERE subscription_id=? LIMIT 1",
                    (subscription_id,),
                ).fetchone()
                if row is None or int(row["enabled"] or 0) != 1:
                    return {"ok": False, "subscription_id": subscription_id, "message": "Assinatura inexistente ou desativada."}
                if int(row["auth_required"] or 0) == 1:
                    return {"ok": False, "subscription_id": subscription_id, "auth_required": True, "message": "Credenciais precisam ser confirmadas antes de retomar."}
                cooldown_until = float(row["cooldown_until"] or 0)
                if cooldown_until > now_epoch:
                    return {
                        "ok": False,
                        "subscription_id": subscription_id,
                        "cooldown": True,
                        "retry_after_seconds": int(cooldown_until - now_epoch),
                        "cooldown_reason": str(row["cooldown_reason"] or "rate_limit"),
                        "message": (
                            "A Leapmotor ainda não liberou uma nova autenticação. O Gateway aguardará automaticamente."
                            if str(row["cooldown_reason"] or "") == "login"
                            else "Proteção contra limite de requisições ainda está ativa."
                        ),
                    }
                current_next = float(row["next_run_at"] or 0)
                current_status = str(row["status"] or "").strip().lower()
                # 1.12.108 — um comando físico que ACABOU de ser aceito não pode
                # herdar 45/120s de uma falha de telemetria anterior. Recovering e
                # error são esperas soft: só o perfil command pode cortá-las. As
                # proteções reais permanecem duras — auth_required é recusado acima
                # e cooldown_until também é recusado antes deste ponto.
                hard_protected_wait = current_status in {"cooldown", "auth_required"} and current_next > now_epoch
                recovery_wait = current_status in {"recovering", "error"} and current_next > now_epoch
                protected_wait = hard_protected_wait or (recovery_wait and profile != "command")
                requested_next = now_epoch + 0.35
                next_run = current_next if protected_wait else (min(current_next, requested_next) if current_next > now_epoch else requested_next)
                interactive_until = now_epoch + seconds if profile == "interactive" else 0.0
                command_until = now_epoch + seconds if profile == "command" else 0.0
                requested_request_id = str(safe_context.get("request_id") or "")
                same_command_window = False
                pending_confirmations = 0
                if profile == "command":
                    self._prune_confirmations(db, now_epoch)
                    _confirmation_id, same_command_window = self._register_confirmation(
                        db,
                        subscription_id,
                        command_key,
                        command_vehicle_id,
                        requested_request_id,
                        command_context_json,
                        seconds,
                        now_epoch,
                        now_iso,
                    )
                    pending_confirmations = len(self._pending_confirmations(db, subscription_id))
                if protected_wait:
                    if profile == "command" and not same_command_window:
                        cursor = db.execute(
                            "UPDATE subscriptions SET active_until=MAX(active_until,?),"
                            "command_until=MAX(command_until,?),command_key=?,command_vehicle_id=?,command_context_json=?,"
                            "command_poll_count=0,command_started_at=?,last_presence_at=?,updated_at=? "
                            "WHERE subscription_id=? AND enabled=1",
                            (
                                now_epoch + seconds,
                                command_until,
                                command_key or None,
                                command_vehicle_id or None,
                                command_context_json,
                                now_epoch,
                                now_iso,
                                now_iso,
                                subscription_id,
                            ),
                        )
                    else:
                        cursor = db.execute(
                            "UPDATE subscriptions SET active_until=MAX(active_until,?),interactive_until=MAX(interactive_until,?),"
                            "command_until=MAX(command_until,?),last_presence_at=?,updated_at=? WHERE subscription_id=? AND enabled=1",
                            (now_epoch + seconds, interactive_until, command_until, now_iso, now_iso, subscription_id),
                        )
                    return {
                        "ok": True,
                        "subscription_id": subscription_id,
                        "profile": profile,
                        "protected_wait": True,
                        "confirmation_window_reused": same_command_window,
                        "retry_after_seconds": max(1, int(current_next - now_epoch)),
                    }
                if profile == "command":
                    if same_command_window:
                        cursor = db.execute(
                            "UPDATE subscriptions SET status='waiting',next_run_at=?,active_until=MAX(active_until,?),"
                            "command_until=MAX(command_until,?),last_presence_at=?,last_error=NULL,updated_at=? "
                            "WHERE subscription_id=? AND enabled=1",
                            (
                                next_run,
                                now_epoch + seconds,
                                command_until,
                                now_iso,
                                now_iso,
                                subscription_id,
                            ),
                        )
                    else:
                        # `command_until` cresce, nunca encolhe: outra confirmação
                        # ainda pendente pode ter uma janela mais longa que esta, e
                        # encurtá-la calaria o veredito dela.
                        cursor = db.execute(
                            "UPDATE subscriptions SET status='waiting', next_run_at=?, active_until=MAX(active_until, ?), "
                            "interactive_until=MAX(interactive_until, ?), command_until=MAX(command_until, ?), command_key=?, command_vehicle_id=?, "
                            "command_context_json=?, command_poll_count=0, command_started_at=?, "
                            "last_presence_at=?, last_error=NULL, updated_at=? WHERE subscription_id=? AND enabled=1",
                            (
                                next_run,
                                now_epoch + seconds,
                                interactive_until,
                                command_until,
                                command_key or None,
                                command_vehicle_id or None,
                                command_context_json,
                                now_epoch,
                                now_iso,
                                now_iso,
                                subscription_id,
                            ),
                        )
                elif profile == "interactive":
                    cursor = db.execute(
                        "UPDATE subscriptions SET status='waiting', next_run_at=?, active_until=MAX(active_until, ?), "
                        "interactive_until=MAX(interactive_until, ?), last_presence_at=?, last_error=NULL, updated_at=? "
                        "WHERE subscription_id=? AND enabled=1",
                        (next_run, now_epoch + seconds, interactive_until, now_iso, now_iso, subscription_id),
                    )
                else:
                    cursor = db.execute(
                        "UPDATE subscriptions SET status='waiting', next_run_at=?, active_until=MAX(active_until, ?), "
                        "last_presence_at=?, last_error=NULL, updated_at=? WHERE subscription_id=? AND enabled=1",
                        (next_run, now_epoch + seconds, now_iso, now_iso, subscription_id),
                    )
        self.wake_event.set()
        return {
            "ok": cursor.rowcount > 0,
            "subscription_id": subscription_id,
            "boost_seconds": seconds,
            "profile": profile,
            "interactive": profile in {"interactive", "command"},
            "command_confirmation": profile == "command",
            "confirmation_window_reused": same_command_window if profile == "command" else False,
            "adaptive_polling": profile == "command",
            "poll_schedule_seconds": list(self.command_effective_cadence) if profile == "command" else [self.interactive_seconds],
            "max_command_polls": self.command_max_polls if profile == "command" else None,
            # Quantos comandos esperam veredito nesta assinatura, contando este.
            # Mais de um deixou de significar que o anterior foi esquecido.
            "pending_confirmations": pending_confirmations if profile == "command" else 0,
        }

    def storage_status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "healthy": bool(self.storage_healthy),
            "path": str(self.db_path),
            "journal_mode": self.storage_journal_mode,
            "consecutive_failures": int(self.storage_failures),
            "last_error": self.storage_last_error or None,
            "last_error_at": self.storage_last_error_at or None,
            "retry_in_seconds": max(0, int(self.storage_next_retry_at - now)),
        }

    def collection_status(self) -> dict[str, Any]:
        """Saturação da coleta paralela, sem tocar no banco.

        1.12.51 — diagnosticar a lentidão anterior exigiu ler o log linha a linha.
        Estes três números respondem de imediato se as coletas estão enfileiradas
        atrás dos workers e se o journal que ficou valendo é o esperado.
        """
        with self._inflight_guard:
            in_flight = len(self._inflight)
        return {
            "poll_workers": int(self.poll_workers),
            "polls_in_flight": in_flight,
            "workers_saturated": in_flight >= int(self.poll_workers),
            "delivery_connection_reused": self._delivery_connection is not None,
            "visual_jobs_pending": int(self._visual_jobs_pending),
            "visual_workers": int(self.visual_render_workers),
            "visual_worker_isolated": True,
            "journal_mode": self.storage_journal_mode,
        }

    def status_fast(self) -> dict[str, Any]:
        """Bounded health snapshot that never holds Cloudflare health checks hostage."""
        acquired = self.lock.acquire(timeout=0.15)
        if not acquired:
            return {
                "ok": True,
                "busy": True,
                "message": "Telemetria ocupada em uma coleta; armazenamento continua ativo.",
                "storage": self.storage_status(),
                "collection": self.collection_status(),
            }
        try:
            with self._db(0.2) as db:
                row = db.execute(
                    "SELECT COUNT(*) subscriptions, "
                    "SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled, "
                    "SUM(CASE WHEN status IN ('error','auth_required') THEN 1 ELSE 0 END) errors "
                    "FROM subscriptions"
                ).fetchone()
                pending = db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0]
            return {
                "ok": True,
                "storage": self.storage_status(),
                "subscriptions": int(row["subscriptions"] or 0),
                "enabled_subscriptions": int(row["enabled"] or 0),
                "subscriptions_with_errors": int(row["errors"] or 0),
                "pending_events": int(pending or 0),
                "collection": self.collection_status(),
            }
        except (OSError, sqlite3.Error) as exc:
            return {
                "ok": True,
                "busy": True,
                "message": "Resumo temporariamente ocupado; o worker permanece ativo.",
                "storage": self.storage_status(),
                "detail": str(exc)[:160],
            }
        finally:
            self.lock.release()

    def status(self) -> dict[str, Any]:
        try:
            with self.lock, self._db() as db:
                totals = db.execute(
                    "SELECT COUNT(*) subscriptions, SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) enabled, "
                    "SUM(CASE WHEN status IN ('error','auth_required') THEN 1 ELSE 0 END) errors, "
                    "SUM(CASE WHEN enabled=1 AND active_until>? THEN 1 ELSE 0 END) active_windows, "
                    "SUM(CASE WHEN enabled=1 AND interactive_until>? THEN 1 ELSE 0 END) interactive_windows, "
                    "SUM(CASE WHEN enabled=1 AND command_until>? THEN 1 ELSE 0 END) command_windows FROM subscriptions",
                    (time.time(), time.time(), time.time()),
                ).fetchone()
                queue = db.execute(
                    "SELECT COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) pending, "
                    "COALESCE(SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END),0) delivered, "
                    "MIN(CASE WHEN status='pending' THEN created_at END) oldest_pending FROM events"
                ).fetchone()
                recent = [dict(row) for row in db.execute(
                    "SELECT subscription_id, environment, account_id, status, last_run_at, last_success_at, last_delivery_at, "
                    "last_error, last_state, next_run_at, active_until, interactive_until, command_until, command_key, command_vehicle_id, command_poll_count, command_started_at, last_presence_at, auth_required, cooldown_until, cooldown_reason, last_auth_attempt_at, last_auth_success_at "
                    "FROM subscriptions ORDER BY updated_at DESC LIMIT 20"
                ).fetchall()]
                dedupe = db.execute(
                    "SELECT COALESCE(SUM(skipped_unchanged),0) skipped, COUNT(*) vehicles, MAX(updated_at) last_state_update FROM vehicle_state_cache"
                ).fetchone()
                recent_states = [dict(row) for row in db.execute(
                    "SELECT subscription_id, remote_id, sequence, skipped_unchanged, last_source_at, updated_at FROM vehicle_state_cache ORDER BY updated_at DESC LIMIT 20"
                ).fetchall()]
                # 1.12.62 — quantos comandos esperam veredito, um por linha. Com
                # a janela única anterior o painel não tinha como mostrar que um
                # segundo comando havia substituído o primeiro.
                pending_confirmations = [dict(row) for row in db.execute(
                    "SELECT confirmation_id, subscription_id, request_id, command_key, command_vehicle_id, "
                    "started_at, expires_at, poll_count, evaluated_samples, stale_samples "
                    "FROM command_confirmations WHERE status='pending' ORDER BY started_at ASC LIMIT 20"
                ).fetchall()]
                recent_confirmations = [dict(row) for row in db.execute(
                    "SELECT confirmation_id, subscription_id, command_key, status, resolution, poll_count, "
                    "evaluated_samples, stale_samples, resolved_at FROM command_confirmations "
                    "WHERE status<>'pending' ORDER BY resolved_at DESC LIMIT 10"
                ).fetchall()]
        except (OSError, sqlite3.Error) as exc:
            self._record_storage_failure(exc)
            return {
                "ok": False,
                "message": "Fila persistente temporariamente indisponível.",
                "storage": self.storage_status(),
                "subscriptions": 0,
                "enabled_subscriptions": 0,
                "pending_events": 0,
                "recent_vehicle_states": [],
                "recent": [],
            }
        self._record_storage_success()
        now_epoch = time.time()
        for item in recent:
            item["next_run_in_seconds"] = max(0, int(float(item.pop("next_run_at") or 0) - now_epoch))
            item["active_for_seconds"] = max(0, int(float(item.pop("active_until") or 0) - now_epoch))
            item["interactive_for_seconds"] = max(0, int(float(item.pop("interactive_until") or 0) - now_epoch))
            item["command_for_seconds"] = max(0, int(float(item.pop("command_until") or 0) - now_epoch))
            item["command_started_seconds_ago"] = max(0, int(now_epoch - float(item.pop("command_started_at") or now_epoch)))
            item["cooldown_seconds"] = max(0, int(float(item.pop("cooldown_until") or 0) - now_epoch))
            item["last_auth_attempt_seconds_ago"] = max(0, int(now_epoch - float(item.pop("last_auth_attempt_at") or now_epoch)))
            last_auth_success = float(item.pop("last_auth_success_at") or 0)
            item["last_auth_success_seconds_ago"] = max(0, int(now_epoch - last_auth_success)) if last_auth_success > 0 else None
            item["session_reused"] = self._has_session(str(item.get("subscription_id") or ""))
            if item.get("last_error"):
                item["last_error"] = str(item["last_error"])[:240]
        return {
            "ok": True,
            "storage": self.storage_status(),
            "subscriptions": int(totals["subscriptions"] or 0),
            "enabled_subscriptions": int(totals["enabled"] or 0),
            "active_windows": int(totals["active_windows"] or 0),
            "interactive_windows": int(totals["interactive_windows"] or 0),
            "command_windows": int(totals["command_windows"] or 0),
            "subscription_errors": int(totals["errors"] or 0),
            "pending_events": int(queue["pending"] or 0),
            "delivered_events": int(queue["delivered"] or 0),
            "oldest_pending": queue["oldest_pending"],
            "deduplicated_events": int(dedupe["skipped"] or 0),
            "tracked_vehicles": int(dedupe["vehicles"] or 0),
            "last_state_update": dedupe["last_state_update"],
            "pending_confirmations": len(pending_confirmations),
            "pending_confirmation_details": [
                {
                    "confirmation_id": str(item.get("confirmation_id") or ""),
                    "subscription_id": str(item.get("subscription_id") or ""),
                    "request_id": str(item.get("request_id") or ""),
                    "command_key": str(item.get("command_key") or ""),
                    "command_vehicle_id": str(item.get("command_vehicle_id") or ""),
                    "poll_count": int(item.get("poll_count") or 0),
                    "evaluated_samples": int(item.get("evaluated_samples") or 0),
                    "stale_samples": int(item.get("stale_samples") or 0),
                    "waiting_for_seconds": max(0, int(now_epoch - float(item.get("started_at") or now_epoch))),
                    "window_left_seconds": max(0, int(float(item.get("expires_at") or 0) - now_epoch)),
                }
                for item in pending_confirmations
            ],
            "recent_confirmations": recent_confirmations,
            "profiles": {
                "driving_seconds": self.active_seconds,
                "interactive_seconds": self.interactive_seconds,
                "command_seconds": self.command_seconds,
                "command_cadence_seconds": list(self.command_cadence),
                "command_effective_cadence_seconds": list(self.command_effective_cadence),
                "command_max_polls": self.command_max_polls,
                "manual_priority": self.manual_pending_provider is not None,
                "collection_profiles": {
                    "fast": "status_and_vehicle_state",
                    "slow": "messages_and_official_visual",
                    "slow_interval_seconds": self.slow_interval_seconds,
                    "degraded_disables_slow": True,
                },
                "charging_seconds": self.charging_seconds,
                "charge_watch_seconds": self.charge_watch_seconds,
                "parked_seconds": self.parked_seconds,
                "sleep_seconds": self.sleep_seconds,
                "background_enabled": self.background_enabled,
                "background_seconds": self.background_seconds,
                "rate_limit_cooldown_seconds": self.rate_limit_cooldown_seconds,
                "auth_attempt_min_interval_seconds": self.auth_attempt_min_interval_seconds,
                "presence_window_seconds": self.presence_window_seconds,
                "presence_driven": not self.background_enabled,
                "presence_role": "fast_mode",
                "session_reuse": True,
            },
            "event_transport": EVENT_TRANSPORT.snapshot(),
            "recent_vehicle_states": recent_states,
            "recent": recent,
        }

    def _record_storage_failure(self, exc: BaseException) -> float:
        self.storage_healthy = False
        self.storage_failures += 1
        message = str(exc).strip() or type(exc).__name__
        self.storage_last_error = message[:240]
        self.storage_last_error_at = utc_iso()
        steps = (2, 5, 10, 20, 30, 60, 120, 300)
        delay = float(steps[min(self.storage_failures - 1, len(steps) - 1)])
        now = time.time()
        self.storage_next_retry_at = now + delay
        if self.storage_failures == 1 or now >= self.storage_next_log_at:
            LOG.error(
                "Fila SQLite indisponível (%s). Nova tentativa em %ss. Caminho: %s",
                self.storage_last_error,
                int(delay),
                self.db_path,
            )
            self.storage_next_log_at = now + max(30.0, delay)
        try:
            self._prepare_storage(probe=True)
        except OSError:
            pass
        return delay

    def _record_storage_success(self) -> None:
        if self.storage_failures > 0:
            LOG.info("Acesso à fila SQLite recuperado em %s.", self.db_path)
        self.storage_healthy = True
        self.storage_failures = 0
        self.storage_last_error = ""
        self.storage_last_error_at = ""
        self.storage_next_retry_at = 0.0
        self.storage_next_log_at = 0.0

    def _run(self) -> None:
        """Escalonador. A coleta vai para o pool; a entrega tem thread própria."""
        while not self.stop_event.is_set():
            did_work = False
            storage_wait: float | None = None
            try:
                did_work = self._dispatch_due_subscriptions()
                self._record_storage_success()
            except (OSError, sqlite3.Error) as exc:
                storage_wait = self._record_storage_failure(exc)
            except Exception:  # noqa: BLE001
                LOG.exception("Falha no ciclo de telemetria")
            if storage_wait is not None:
                wait = storage_wait
            else:
                try:
                    wait = 0.5 if did_work else min(5.0, self._seconds_until_next())
                except (OSError, sqlite3.Error) as exc:
                    wait = self._record_storage_failure(exc)
            self.wake_event.wait(max(0.25, wait))
            self.wake_event.clear()

    def _run_maintenance(self) -> None:
        """Retencao best-effort: nunca compete de forma perceptivel com comando."""
        # Depois de restart, sincronizacao, login e primeiros comandos sao mais
        # importantes que podar eventos antigos. A fila continua persistente.
        if self.stop_event.wait(MAINTENANCE_STARTUP_GRACE_SECONDS):
            return
        while not self.stop_event.is_set():
            started = time.monotonic()
            outcome = "unknown"
            try:
                outcome = str(self._maintenance() or "ok")
            except (OSError, sqlite3.Error) as exc:
                # Manutencao nao representa saude do scheduler. SQLite ocupado
                # significa apenas ceder e tentar depois; nao dispara 503 global.
                outcome = "sqlite_busy"
                LOG.debug(
                    "Manutencao local cedeu por SQLite ocupado: %s",
                    connector.clean_message(str(exc)),
                )
            except Exception:  # noqa: BLE001
                outcome = "error"
                LOG.exception("Falha no worker isolado de manutencao")
            elapsed_ms = int(round((time.monotonic() - started) * 1000))
            if elapsed_ms >= TELEMETRY_STAGE_LOG_THRESHOLD_MS:
                LOG.info(
                    "TELEMETRY_MAINTENANCE_DIAG elapsed_ms=%s outcome=%s",
                    elapsed_ms,
                    outcome,
                )
            if self.stop_event.wait(MAINTENANCE_WORKER_POLL_SECONDS):
                break

    def _run_delivery(self) -> None:
        """Entrega ao site em thread dedicada.

        1.12.50 — o POST tem timeout próprio e a hospedagem do site pode demorar.
        Enquanto ele morava no laço principal, uma lentidão do site parava a
        coleta de todas as contas pelo mesmo tempo.
        """
        while not self.stop_event.is_set():
            wait = 2.0
            try:
                if self._deliver_due():
                    wait = 0.25
                # A recuperação do armazenamento é declarada apenas pelo
                # escalonador, que abre o banco em todo ciclo. Duas threads
                # zerando o mesmo contador só produziria log oscilante.
            except (OSError, sqlite3.Error) as exc:
                wait = self._record_storage_failure(exc)
            except Exception:  # noqa: BLE001
                LOG.exception("Falha na entrega de telemetria")
                wait = 5.0
            self.delivery_event.wait(max(0.25, wait))
            self.delivery_event.clear()

    def _dispatch_due_subscriptions(self) -> bool:
        """Entrega ao pool as assinaturas vencidas que ainda não estão em coleta."""
        pool = self._poll_pool
        if pool is None:
            return False
        dispatched = False
        while not self.stop_event.is_set():
            with self._inflight_guard:
                free = self.poll_workers - len(self._inflight)
            if free <= 0:
                break
            subscription = self._next_due_subscription()
            if subscription is None:
                break
            sid = str(subscription["subscription_id"])
            with self._inflight_guard:
                if sid in self._inflight:
                    break
                self._inflight.add(sid)
            dispatched = True
            pool.submit(self._poll_subscription_guarded, subscription, sid)
        return dispatched

    def _poll_subscription_guarded(self, subscription: sqlite3.Row, sid: str) -> None:
        try:
            self._poll_subscription(subscription)
        except (OSError, sqlite3.Error) as exc:
            self._record_storage_failure(exc)
        except Exception:  # noqa: BLE001
            LOG.exception("Falha ao consultar a assinatura %s", sid)
        finally:
            with self._inflight_guard:
                self._inflight.discard(sid)
            self.wake_event.set()

    def _next_due_subscription(self) -> sqlite3.Row | None:
        # A ordem de prioridade (comando -> interativo -> fundo) é preservada.
        # Uma assinatura já em coleta mantém next_run_at no passado até reagendar;
        # o conjunto _inflight é o que impede coleta duplicada da mesma conta.
        with self._inflight_guard:
            busy = set(self._inflight)
        with self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS) as db:
            now_epoch = time.time()
            active_filter = "" if self.background_enabled else " AND active_until>?"
            parameters: tuple[float, ...]
            if self.background_enabled:
                parameters = (now_epoch, now_epoch, now_epoch)
            else:
                parameters = (now_epoch, now_epoch, now_epoch, now_epoch)
            rows = db.execute(
                "SELECT * FROM subscriptions WHERE enabled=1 AND auth_required=0"
                + active_filter
                + " AND next_run_at<=? "
                "ORDER BY CASE WHEN command_until>? THEN 0 WHEN interactive_until>? THEN 1 ELSE 2 END, next_run_at ASC LIMIT 12",
                parameters,
            ).fetchall()
        for row in rows:
            if str(row["subscription_id"]) not in busy:
                due = float(row["next_run_at"] or now_epoch)
                late_ms = int(round(max(0.0, now_epoch - due) * 1000))
                if float(row["command_until"] or 0) > now_epoch and late_ms >= TELEMETRY_STAGE_LOG_THRESHOLD_MS:
                    LOG.info(
                        "CONFIRM_SCHED_DIAG stage=due_dispatch late_ms=%s subscription=%s",
                        late_ms, str(row["subscription_id"] or "")[:96],
                    )
                return row
        return None

    def _seconds_until_next(self) -> float:
        with self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS) as db:
            if self.background_enabled:
                row = db.execute(
                    "SELECT MIN(next_run_at) due FROM subscriptions WHERE enabled=1 AND auth_required=0"
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT MIN(next_run_at) due FROM subscriptions WHERE enabled=1 AND auth_required=0 AND active_until>?",
                    (time.time(),),
                ).fetchone()
            delivery = db.execute("SELECT MIN(next_attempt_at) due FROM events WHERE status='pending'").fetchone()
        values = [float(item["due"]) for item in (row, delivery) if item and item["due"] is not None]
        return max(0.25, min(values) - time.time()) if values else 5.0

    def _reconcile_live_post_poll_schedule(
        self,
        db: sqlite3.Connection,
        subscription: sqlite3.Row,
        cycle_epoch: float,
        proposed_next_run: float,
        proposed_command_poll: int,
    ) -> tuple[float, int, int, bool, bool]:
        """Mescla somente coordenação que nasceu depois do snapshot deste poll.

        A chamada à nuvem termina antes do processamento/persistência local. Ao
        liberar a trava da conta, um comando manual pode ser aceito e o arme
        assíncrono pode gravar ``next_run_at ~= agora + 0.35`` enquanto este poll
        ainda finaliza. Sem reler a linha viva, o snapshot antigo sobrescreve
        essa agenda com 45/90/600s e também pode trocar o poll_count novo por um
        contador velho.

        O mesmo interleaving pode criar cooldown/auth_required depois da leitura
        que acabou de ter sucesso. Esses bloqueios são mais novos que o snapshot
        e nunca podem ser apagados por ele.
        """
        sid = str(subscription["subscription_id"] or "")
        live = db.execute(
            "SELECT status,next_run_at,command_until,command_started_at,command_poll_count,"
            "auth_required,cooldown_until FROM subscriptions WHERE subscription_id=? LIMIT 1",
            (sid,),
        ).fetchone()
        pending = db.execute(
            "SELECT COUNT(*) AS total,MAX(started_at) AS newest_started_at "
            "FROM command_confirmations WHERE subscription_id=? AND status='pending' AND expires_at>?",
            (sid, cycle_epoch),
        ).fetchone()

        pending_total = int(pending["total"] or 0) if pending is not None else 0
        newest_started_at = float(pending["newest_started_at"] or 0) if pending is not None else 0.0
        snapshot_started_at = float(subscription["command_started_at"] or 0)
        newer_command_armed = pending_total > 0 and newest_started_at > snapshot_started_at + 0.000001

        next_run = float(proposed_next_run)
        command_poll = int(proposed_command_poll)
        hard_protection = False
        if live is not None:
            hard_protection = (
                int(live["auth_required"] or 0) == 1
                or float(live["cooldown_until"] or 0) > cycle_epoch
            )
            if newer_command_armed and not hard_protection:
                live_next = float(live["next_run_at"] or 0)
                if live_next > 0:
                    # O valor pode já estar vencido quando o poll termina. Isso
                    # é intencional: _inflight impediu duplicata; ao liberar a
                    # assinatura, o scheduler deve executar a FAST imediatamente.
                    next_run = min(next_run, live_next)
                command_poll = max(0, int(live["command_poll_count"] or 0))

        return next_run, command_poll, pending_total, hard_protection, newer_command_armed


    def _poll_subscription(self, subscription: sqlite3.Row) -> None:
        sid = str(subscription["subscription_id"])
        now_epoch = time.time()
        active_until = float(subscription["active_until"] or 0)
        presence_active = active_until > now_epoch
        interactive = float(subscription["interactive_until"] or 0) > now_epoch
        command_mode = float(subscription["command_until"] or 0) > now_epoch
        fast_mode = interactive or command_mode
        if not presence_active and not self.background_enabled:
            # O fim da janela ativa pausa novas leituras, mas não encerra uma
            # sessão saudável. Fechar aqui obrigava um novo login a cada janela.
            with self.lock, self._db() as db:
                db.execute(
                    "UPDATE subscriptions SET status='idle', next_run_at=?, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, last_error=NULL, updated_at=? WHERE subscription_id=?",
                    (now_epoch + self.sleep_seconds, utc_iso(), sid),
                )
            return

        with self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS) as db:
            queued = int(db.execute("SELECT COUNT(*) FROM events WHERE status='pending'").fetchone()[0])
        if queued >= self.queue_max:
            self._reschedule(sid, 300, "queue_full", "Fila persistente atingiu o limite; aguardando entrega ao site.", failed=False)
            LOG.error("Fila de telemetria cheia (%s eventos). Coleta pausada até a entrega liberar espaço.", queued)
            return

        environment = str(subscription["environment"])
        account_id = int(subscription["account_id"] or 0)
        # 1.12.47 — backpressure primeiro por conta. Uma única conta com
        # timeout/retry repetido reduz somente a própria telemetria de fundo.
        # O breaker global abaixo exige evidência de contas distintas.
        if (
            not fast_mode
            and ORCHESTRATOR.is_account_degraded(environment, account_id)
            and not ORCHESTRATOR.claim_account_background_probe(environment, account_id)
        ):
            self._reschedule(
                sid,
                60,
                "account_cloud_degraded",
                "Esta conta está em recuperação temporária; outras contas continuam com a cadência normal.",
                failed=False,
            )
            return

        # Breaker compartilhado: só reduz o ambiente quando contas distintas
        # falham na mesma janela, sinalizando indisponibilidade realmente comum.
        if not fast_mode and ORCHESTRATOR.is_degraded(environment) and not ORCHESTRATOR.claim_background_probe(environment):
            self._reschedule(
                sid,
                60,
                "cloud_degraded",
                "Nuvem Leapmotor degradada em múltiplas contas; telemetria automática reduzida sem afetar comandos manuais.",
                failed=False,
            )
            return
        global_auth = self.account_auth_status(environment, account_id)
        if global_auth.get("cooldown"):
            self._reschedule(
                sid,
                max(30, int(global_auth.get("retry_after_seconds") or 30)),
                "cooldown",
                "Cooldown desta conta ativo; as demais contas continuam independentes.",
                failed=False,
            )
            return
        cooldown_until = float(subscription["cooldown_until"] or 0)
        if cooldown_until > now_epoch:
            self._reschedule(sid, max(30, int(cooldown_until - now_epoch)), "cooldown", "Proteção de limite ativa; aguardando antes da próxima consulta.", failed=False)
            return
        if not self.environment_enabled.get(environment, False) or not self.delivery_urls.get(environment):
            self._close_session(sid)
            self._reschedule(sid, self.sleep_seconds, "disabled", "URL de entrega ou ambiente desativado.", failed=False)
            return
        try:
            credentials = json.loads(self.fernet.decrypt(bytes(subscription["credentials_encrypted"])).decode("utf-8"))
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._close_session(sid)
            self._mark_auth_required(sid, "Credenciais locais não puderam ser descriptografadas.")
            LOG.error("Assinatura %s com credencial inválida: %s", sid, exc)
            return
        try:
            vehicle_ids = set(json.loads(str(subscription["vehicle_ids_json"])))
        except (ValueError, TypeError, json.JSONDecodeError):
            vehicle_ids = set()
        command_target_vehicle = str(subscription["command_vehicle_id"] or "").strip()
        if command_mode:
            # 1.12.62 — a leitura tem de cobrir o alvo de TODAS as esperas.
            # Restringir ao veículo do último comando cegava as demais: a
            # confirmação de um comando anterior, em outro carro da mesma conta,
            # nunca receberia amostra para avaliar.
            with self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS) as db:
                pending_targets = [
                    str(row["command_vehicle_id"] or "").strip()
                    for row in self._pending_confirmations(db, sid)
                ]
            if command_target_vehicle:
                pending_targets.append(command_target_vehicle)
            # Espera sem alvo definido vale para qualquer veículo: nesse caso não
            # há o que restringir.
            if pending_targets and all(pending_targets):
                vehicle_ids = set(pending_targets)

        operation_payload = {
            "account_id": int(subscription["account_id"] or 0),
            "credentials": credentials,
        }
        # Uma leitura automática nunca abre outra autenticação poucos segundos
        # depois da anterior. Isso vale inclusive após reiniciar o App, pois o
        # horário fica persistido na assinatura. Comandos manuais continuam com
        # prioridade e usam o fluxo próprio.
        last_auth_attempt_at = float(subscription["last_auth_attempt_at"] or 0) if "last_auth_attempt_at" in subscription.keys() else 0.0
        if not command_mode and not self._has_session(sid) and last_auth_attempt_at > 0:
            remaining = self.auth_attempt_min_interval_seconds - int(now_epoch - last_auth_attempt_at)
            if remaining > 0:
                credentials.clear()
                self._reschedule(
                    sid,
                    max(5, remaining),
                    "waiting_auth",
                    "Aguardando o intervalo seguro antes de uma nova autenticação automática.",
                    failed=False,
                )
                return
        if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
            credentials.clear()
            self._reschedule(sid, 2, "waiting", "Comando do usuário tem prioridade sobre a telemetria automática.", failed=False)
            return

        # 1.12.47 — ordem única de aquisição: conta -> vaga global.
        # Antes a telemetria podia segurar uma vaga global enquanto aguardava
        # a trava de uma conta ocupada, invertendo a ordem usada pelos comandos
        # manuais. Isso permitia uma conta lenta consumir capacidade de outras.
        queue_started_at = time.monotonic()
        account_wait_ms = 0.0
        connector_slot_ms = 0.0
        account_lock = None
        account_acquired = False
        acquired = False
        if self.account_lock_provider is not None:
            account_lock = self.account_lock_provider(environment, operation_payload)
            account_wait_started_at = time.monotonic()
            account_acquired = account_lock.acquire(timeout=self.account_wait_seconds)
            account_wait_ms = (time.monotonic() - account_wait_started_at) * 1000.0
            if not account_acquired:
                credentials.clear()
                ORCHESTRATOR.record_telemetry_cycle(
                    environment,
                    profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                    duration_ms=0.0,
                    outcome="account_busy_yield",
                    account_wait_ms=account_wait_ms,
                    connector_slot_ms=0.0,
                )
                self._reschedule(
                    sid,
                    15,
                    "waiting",
                    "A conta já está sendo consultada por outra operação; nenhuma vaga global foi ocupada enquanto aguardava.",
                    failed=False,
                )
                return

        if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
            if account_acquired and account_lock is not None:
                account_lock.release()
            credentials.clear()
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=0.0,
                outcome="manual_yield",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=0.0,
            )
            self._reschedule(sid, 2, "waiting", "Comando do usuário aguardando execução; telemetria liberou a conta antes de usar uma vaga global.", failed=False)
            return

        slot_wait_started_at = time.monotonic()
        slot_deadline = slot_wait_started_at + 5.0
        while True:
            acquired = self.operation_semaphore.acquire(timeout=0.25)
            if acquired:
                break
            if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
                if account_acquired and account_lock is not None:
                    account_lock.release()
                credentials.clear()
                connector_slot_ms = (time.monotonic() - slot_wait_started_at) * 1000.0
                ORCHESTRATOR.record_telemetry_cycle(
                    environment,
                    profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                    duration_ms=0.0,
                    outcome="manual_yield",
                    account_wait_ms=account_wait_ms,
                    connector_slot_ms=connector_slot_ms,
                )
                self._reschedule(sid, 2, "waiting", "Telemetria liberou a conta para um comando manual antes de ocupar o Connector.", failed=False)
                return
            if time.monotonic() >= slot_deadline:
                if account_acquired and account_lock is not None:
                    account_lock.release()
                credentials.clear()
                connector_slot_ms = (time.monotonic() - slot_wait_started_at) * 1000.0
                ORCHESTRATOR.record_telemetry_cycle(
                    environment,
                    profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                    duration_ms=0.0,
                    outcome="slot_timeout",
                    account_wait_ms=account_wait_ms,
                    connector_slot_ms=connector_slot_ms,
                )
                self._reschedule(sid, 30, "waiting", "Aguardando vaga no Connector; a conta foi liberada para não bloquear comandos.", failed=False)
                return

        connector_slot_ms = (time.monotonic() - slot_wait_started_at) * 1000.0
        if self._manual_operation_blocks(environment, operation_payload, command_mode=command_mode):
            self.operation_semaphore.release()
            if account_acquired and account_lock is not None:
                account_lock.release()
            credentials.clear()
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=0.0,
                outcome="manual_yield",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=connector_slot_ms,
            )
            self._reschedule(sid, 2, "waiting", "Comando do usuário aguardando execução; telemetria cedeu a vaga imediatamente.", failed=False)
            return
        manual_provider = self.manual_active_provider if command_mode else self.manual_pending_provider
        manual_should_yield = (
            (lambda: bool(manual_provider and manual_provider(environment, operation_payload)))
            if manual_provider is not None
            else None
        )
        collection_started_at = time.monotonic()
        try:
            result = self._collect_with_session(
                sid,
                environment,
                int(subscription["account_id"] or 0),
                credentials,
                vehicle_ids,
                command_mode=command_mode,
                manual_should_yield=manual_should_yield,
                allow_slow_network=not (interactive or command_mode),
            )
            log_slow_telemetry_stage(
                sid,
                "collection_total",
                collection_started_at,
                origin="confirmation" if command_mode else ("interactive" if interactive else "background"),
            )
        except TelemetryYieldForManual:
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=(time.monotonic() - collection_started_at) * 1000.0,
                outcome="manual_yield",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=connector_slot_ms,
            )
            self._reschedule(sid, 2, "waiting", "Telemetria cedeu a conta para o comando do usuário.", failed=False)
            LOG.info("Telemetria de %s interrompida em ponto seguro para priorizar comando manual.", sid)
            return
        except Exception as exc:  # noqa: BLE001
            ORCHESTRATOR.record_telemetry_cycle(
                environment,
                profile="confirmation" if command_mode else ("interactive" if interactive else "background"),
                duration_ms=(time.monotonic() - collection_started_at) * 1000.0,
                outcome="failure",
                account_wait_ms=account_wait_ms,
                connector_slot_ms=connector_slot_ms,
            )
            message = connector.clean_message(str(exc))
            failures = int(subscription["consecutive_failures"] or 0) + 1
            transient = connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError)
            if not transient or failures >= 3:
                self._close_session(sid)
            if isinstance(exc, connector.ConnectorSessionExpiredError):
                delay = 20
                self._reschedule(
                    sid,
                    delay,
                    "waiting_auth",
                    "Sessão expirada; uma única reconexão protegida foi agendada.",
                    failed=False,
                )
                LOG.info("Sessão de %s expirou; uma reconexão coordenada ocorrerá em %ss.", sid, delay)
                return
            if isinstance(exc, connector.ConnectorLoginCooldownError):
                delay = max(30, min(self.login_cooldown_max_seconds, int(exc.retry_after_seconds or 300)))
                self._apply_account_subscription_cooldown(
                    environment, int(subscription["account_id"] or 0), delay, message, "login"
                )
                LOG.warning(
                    "Autenticação de %s aguardará %ss pelo coordenador global; nenhuma origem chamará a nuvem antes disso.",
                    sid, delay,
                )
            elif self._looks_rate_limited(message):
                requested_delay = connector.rate_limit_cooldown_seconds(message, self.rate_limit_cooldown_seconds)
                if requested_delay <= 0:
                    requested_delay = self.rate_limit_cooldown_seconds
                delay = self.record_account_auth_failure(
                    environment, int(subscription["account_id"] or 0), "telemetry_rate_limit",
                    message, requested_delay, blocked=True,
                )
                LOG.warning("Proteção da conta contra limite ativada para %s por %ss: %s", sid, delay, message)
            elif isinstance(exc, connector.ConnectorAuthenticationError) or connector.is_authentication_error(exc):
                self._mark_auth_required(sid, message)
                LOG.warning("A assinatura %s foi pausada até as credenciais serem confirmadas: %s", sid, message)
            elif transient:
                ORCHESTRATOR.record_cloud_failure(environment, account_id)
                verification_challenge = any(marker in message.lower() for marker in (
                    "information verification failed",
                    "please try again later",
                ))
                if verification_challenge:
                    # Logo após um comando a nuvem pode invalidar o token usado
                    # na leitura anterior. Em janela de confirmação, encerra a
                    # sessão e tenta uma única reconexão moderada antes de adotar
                    # o backoff conservador normal.
                    self._close_session(sid)
                    schedule = (30, 60, 180, 600, 1800, 3600) if command_mode else (120, 300, 900, 1800, 3600, 10800)
                    delay = schedule[min(max(1, failures) - 1, len(schedule) - 1)]
                else:
                    delay = self._transient_backoff(failures, fast_mode, command_mode=command_mode)
                if command_mode:
                    delay = self._within_command_window(
                        delay, float(subscription["command_until"] or 0), time.time()
                    )
                self._reschedule(sid, delay, "recovering", message, failed=True)
                if failures >= 3:
                    LOG.warning("Sessão Leapmotor de %s será refeita após %ss por falhas temporárias repetidas: %s", sid, delay, message)
                else:
                    LOG.warning("Falha temporária em %s; sessão preservada e nova leitura em %ss: %s", sid, delay, message)
            else:
                delay = self._failure_backoff(failures)
                if command_mode:
                    delay = self._within_command_window(
                        delay, float(subscription["command_until"] or 0), time.time()
                    )
                self._reschedule(sid, delay, "error", message, failed=True)
            return
        finally:
            # Libera primeiro o recurso global; a trava da conta sai logo depois.
            # A ordem inversa de aquisição nunca é usada em nenhum caminho.
            self.operation_semaphore.release()
            if account_acquired and account_lock is not None:
                account_lock.release()
            credentials.clear()

        collection_profile = str(result.get("collection_profile") or ("confirmation" if command_mode else "fast"))
        ORCHESTRATOR.record_telemetry_cycle(
            environment,
            profile="confirmation" if command_mode else collection_profile,
            duration_ms=(time.monotonic() - collection_started_at) * 1000.0,
            outcome="success",
            account_wait_ms=account_wait_ms,
            connector_slot_ms=connector_slot_ms,
        )
        ORCHESTRATOR.record_cloud_success(environment, account_id)
        vehicles = [item for item in (result.get("vehicles") or []) if isinstance(item, dict)]
        if vehicle_ids:
            vehicles = [item for item in vehicles if str(item.get("remote_id") or "") in vehicle_ids]
        if not vehicles:
            self._close_session(sid)
            empty_delay = self._failure_backoff(int(subscription["consecutive_failures"] or 0) + 1)
            if command_mode:
                empty_delay = self._within_command_window(
                    empty_delay, float(subscription["command_until"] or 0), time.time()
                )
            self._reschedule(sid, empty_delay, "error", "Nenhum veículo autorizado foi retornado.", failed=True)
            return

        states: list[str] = []
        activity_parts: list[str] = []
        queued_events = 0
        skipped_events = 0
        for vehicle in vehicles:
            telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
            source_at = str(telemetry.get("captured_at") or utc_iso())
            state = self._state_of(telemetry)
            states.append(state)
            activity_parts.append(self.activity_fingerprint(telemetry))
            # Durante a confirmação de comando, até um snapshot semanticamente
            # idêntico precisa chegar ao site. Ex.: `unlock` solicitado quando o
            # carro já estava destravado. Suprimir essa amostra deixava a
            # interface presa em confirmation_pending e também escondia a base
            # necessária para reconciliar um auto-lock posterior.
            queued = self._queue_event(
                subscription,
                vehicle,
                source_at,
                state,
                interactive=fast_mode,
                force_delivery=command_mode,
            )
            if queued.get("queued"):
                queued_events += 1
            else:
                skipped_events += 1
            # A telemetria já foi persistida e, neste ponto, o finally da coleta
            # já liberou vaga global + account lock. Só agora a imagem é pedida.
            self._queue_visual_render(
                subscription,
                vehicle,
                source_at,
                state,
                interactive=fast_mode,
            )

        previous_state = str(subscription["last_state"] or "")
        current_command_poll = int(subscription["command_poll_count"] or 0)
        # 1.12.62 — esta leitura é oferecida a TODOS os comandos que aguardam
        # veredito, e não só ao último. Antes existia uma janela por assinatura:
        # o segundo comando apagava o contexto do primeiro, que ficava sem
        # confirmação e sem recusa. Cada espera tem hora de partida, orçamento e
        # contagem próprios.
        cycle_epoch = time.time()
        outcomes: list[dict[str, Any]] = []
        if command_mode:
            with self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS) as db:
                self._adopt_legacy_confirmation(db, subscription, cycle_epoch)
                pending_rows = self._pending_confirmations(db, sid)
            for entry in pending_rows:
                outcomes.append(self._evaluate_confirmation(entry, vehicles, cycle_epoch))

        confirmed_outcomes = [item for item in outcomes if item["confirmed"]]
        exhausted_outcomes = [item for item in outcomes if not item["confirmed"] and item["exhausted"]]
        remaining_outcomes = [item for item in outcomes if not item["confirmed"] and not item["exhausted"]]
        command_confirmed = bool(confirmed_outcomes)
        command_budget_exhausted = bool(exhausted_outcomes)
        # A janela rápida vale enquanto alguém ainda espera. Um comando recém
        # enviado não é encurtado porque outro, mais antigo, acabou de fechar.
        effective_command_mode = command_mode and bool(remaining_outcomes)
        if remaining_outcomes:
            # A cadência acompanha a espera mais nova: ela ainda merece leituras
            # curtas mesmo que outra, mais velha, já esteja no fim do orçamento.
            next_command_poll = min(int(item["poll_count"]) for item in remaining_outcomes)
        elif outcomes:
            next_command_poll = max(int(item["poll_count"]) for item in outcomes)
        else:
            next_command_poll = current_command_poll + 1 if command_mode else 0
        # 1.12.65 — a contagem para "dormindo" mede tempo parado, não sono. Se
        # as aberturas ou a tranca mudaram desde a leitura anterior, alguém
        # mexeu no carro agora: ele está acordado e volta à cadência rápida.
        activity_signature = "||".join(activity_parts)
        previous_activity = self._ACTIVITY_REGISTRY.get(sid)
        activity_changed = previous_activity is not None and previous_activity != activity_signature
        self._ACTIVITY_REGISTRY[sid] = activity_signature
        interval, observed_state, parked_streak = self._adaptive_interval(
            states,
            self.parked_streak_after_activity(
                int(subscription["parked_streak"] or 0), activity_changed
            ),
            interactive=interactive,
            command_mode=effective_command_mode,
            command_poll_count=next_command_poll,
        )
        # 1.12.96: _adaptive_interval preserva a cadencia estrutural historica.
        # Somente o agendamento real da janela pos-comando recebe 5/5/8.
        if effective_command_mode:
            cadence_index = min(max(1, int(next_command_poll)) - 1, len(self.command_effective_cadence) - 1)
            interval = int(self.command_effective_cadence[cadence_index])
        aggregate_state, candidate_state, candidate_count = self._confirm_state_transition(
            str(subscription["last_state"] or ""),
            str(subscription["candidate_state"] or ""),
            int(subscription["candidate_count"] or 0),
            observed_state,
        )
        if aggregate_state != observed_state and not effective_command_mode:
            interval, _, parked_streak = self._adaptive_interval(
                [aggregate_state],
                self.parked_streak_after_activity(
                    int(subscription["parked_streak"] or 0), activity_changed
                ),
                interactive=interactive,
            )
        previous_sleep_streak = int(subscription["sleep_streak"] or 0)
        sleep_streak = previous_sleep_streak + 1 if aggregate_state == "sleep" else 0
        if aggregate_state == "sleep" and not effective_command_mode:
            interval = self.sleep_seconds if sleep_streak < 3 else max(self.sleep_seconds, min(900, int(self.sleep_seconds * 1.5)))
        if self.background_enabled and not presence_active and not effective_command_mode:
            interval = min(interval, self.background_seconds)
        jitter = random.uniform(0, 0.25) if effective_command_mode else random.uniform(0, min(4.0, max(0.5, interval * 0.04)))
        now = utc_iso()
        next_run = time.time() + interval + jitter
        clear_expired_command = not command_mode and float(subscription["command_until"] or 0) > 0
        # As colunas antigas só são zeradas quando ninguém mais espera veredito.
        clear_command = (command_mode and not remaining_outcomes) or clear_expired_command
        with self.schedule_lock, self._db(timeout_seconds=2.0) as db:
            for item in outcomes:
                self._persist_confirmation(db, item, cycle_epoch, now)
            abandoned = self._prune_confirmations(db, cycle_epoch)
            if clear_expired_command:
                # A janela venceu sem nova leitura: quem sobrou não recebe mais
                # amostra nenhuma e precisa ser encerrado explicitamente, senão
                # a linha fica pendente para sempre. Só as vencidas: um comando
                # que chegou durante esta coleta tem prazo no futuro e não pode
                # ser encerrado por uma decisão tomada antes de ele existir.
                db.execute(
                    "UPDATE command_confirmations SET status='expired',resolution='window_expired',resolved_at=?,updated_at=? "
                    "WHERE subscription_id=? AND status='pending' AND expires_at<=?",
                    (cycle_epoch, now, sid, cycle_epoch),
                )
            # A decisão de limpar veio do retrato da assinatura lido antes da
            # chamada à nuvem, que leva segundos. Um comando enviado nesse
            # intervalo já tem espera viva no banco — e zerar as colunas aqui
            # tiraria a assinatura do modo comando, deixando essa espera órfã
            # até ser recolhida por abandono. É o mesmo veredito perdido que
            # esta versão existe para acabar.
            (
                next_run,
                next_command_poll,
                live_pending_count,
                hard_live_protection,
                newer_command_armed,
            ) = self._reconcile_live_post_poll_schedule(
                db,
                subscription,
                cycle_epoch,
                next_run,
                next_command_poll,
            )
            if live_pending_count > 0:
                clear_command = False
            if hard_live_protection:
                # Uma proteção criada depois da coleta (por exemplo, um comando
                # que recebeu cooldown enquanto este poll fazia trabalho local)
                # vence o snapshot antigo. Atualizamos apenas o fato verdadeiro
                # de que ESTA leitura teve sucesso; status/agenda/erro/proteção
                # permanecem como o produtor mais novo gravou.
                db.execute(
                    "UPDATE subscriptions SET last_run_at=?,last_success_at=?,last_state=?,parked_streak=?,"
                    "candidate_state=?,candidate_count=?,sleep_streak=?,updated_at=? WHERE subscription_id=?",
                    (
                        now,
                        now,
                        aggregate_state,
                        parked_streak,
                        candidate_state or None,
                        candidate_count,
                        sleep_streak,
                        now,
                        sid,
                    ),
                )
            elif clear_command:
                db.execute(
                    "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, candidate_state=?, candidate_count=?, sleep_streak=?, consecutive_failures=0, cooldown_until=0, cooldown_reason=NULL, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, updated_at=? WHERE subscription_id=?",
                    (next_run, now, now, aggregate_state, parked_streak, candidate_state or None, candidate_count, sleep_streak, now, sid),
                )
            else:
                db.execute(
                    "UPDATE subscriptions SET status='active', next_run_at=?, last_run_at=?, last_success_at=?, last_error=NULL, last_state=?, parked_streak=?, candidate_state=?, candidate_count=?, sleep_streak=?, consecutive_failures=0, cooldown_until=0, cooldown_reason=NULL, command_poll_count=?, updated_at=? WHERE subscription_id=?",
                    (next_run, now, now, aggregate_state, parked_streak, candidate_state or None, candidate_count, sleep_streak, next_command_poll, now, sid),
                )
        if abandoned:
            LOG.info(
                "%s confirmação(ões) sem janela ativa foram encerradas por prazo durante o ciclo de %s.",
                abandoned,
                sid,
            )
        for item in confirmed_outcomes:
            # 1.12.100 - estado fisico provado; apenas avise o site.
            self._announce_telemetry_confirmation_async(environment, item)
            # 1.12.70 — o tempo até confirmar entra na linha. Era o número que a
            # análise de campo tinha de reconstruir somando carimbos de hora de
            # linhas diferentes, e é ele que diz se a janela está funcionando.
            LOG.info(
                "Comando %s (%s) confirmado pela telemetria de %s após %s leitura(s) e %ss; "
                "%s comando(s) ainda aguardam.",
                item["command_key"],
                item["request_id"] or "sem request_id",
                sid,
                item["poll_count"],
                int(item["elapsed"]),
                len(remaining_outcomes),
            )
        for item in exhausted_outcomes:
            if item["command_vehicle_id"] and not item["target_seen"]:
                LOG.warning(
                    "Janela rápida de %s não encontrou o veículo-alvo de %s entre os dados retornados; assinatura será reconciliada pelo site.",
                    sid,
                    item["command_key"],
                )
            LOG.warning(
                "Janela rápida de %s encerrada para %s após %s leitura(s) e %ss sem confirmação conclusiva (%s).",
                sid,
                item["command_key"],
                item["poll_count"],
                int(item["elapsed"]),
                "orçamento de leituras esgotado" if item["reason"] == "poll_budget" else "prazo da janela vencido",
            )
            # 1.12.56 — a linha acima diz que falhou; esta diz por quê.
            # 1.12.60 — ganhou o atraso da amostra: com "descartadas por idade"
            # sozinho não se sabia se o carro estava 3 segundos ou 3 horas atrás
            # do comando, e é essa distância que diz se ele sequer acordou.
            LOG.warning(
                "Confirmação inconclusiva de %s em %s: amostras avaliadas=%s, descartadas por idade=%s, "
                "amostra mais recente %s, campos exigidos sem valor=[%s], chaves presentes na telemetria=[%s].",
                item["command_key"] or "desconhecido",
                sid,
                item["evaluated_samples"],
                item["stale_samples"],
                "sem carimbo de hora" if item["sample_lag"] is None
                else ("%.0fs antes do comando" % item["sample_lag"] if item["sample_lag"] > 0
                      else "%.0fs depois do comando" % abs(item["sample_lag"])),
                ", ".join(item["field_gaps"]) or "nenhum",
                ", ".join(item["available_keys"]) or "nenhuma",
            )
        if command_confirmed or command_budget_exhausted:
            # As linhas por comando acima já contam o ciclo.
            pass
        elif previous_state != aggregate_state:
            LOG.info("Telemetria %s mudou de %s para %s; próxima consulta em %ss.", sid, previous_state or "inicial", aggregate_state, int(interval + jitter))
        else:
            LOG.debug(
                "Telemetria %s: sessão reutilizada, %s veículo(s), estado %s, %s evento(s) enfileirado(s), %s leitura(s) idêntica(s) suprimida(s), próxima consulta em %ss%s.",
                sid, len(vehicles), aggregate_state, queued_events, skipped_events, int(interval + jitter),
                " (confirmação adaptativa)" if effective_command_mode else "",
            )
        self.wake_event.set()

    def _queue_visual_render(
        self,
        subscription: Any,
        vehicle: dict[str, Any],
        source_at: str,
        state: str,
        *,
        interactive: bool,
    ) -> bool:
        """Queue a local render only after the state event has been persisted."""
        telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
        signature = str(telemetry.get("visual_signature") or "").strip()
        remote_id = str(vehicle.get("remote_id") or "").strip()[:190]
        if not signature or not remote_id:
            return False
        pool = self._visual_render_pool
        if pool is None:
            return False

        subscription_snapshot = {
            "environment": str(subscription["environment"]),
            "account_id": int(subscription["account_id"]),
            "subscription_id": str(subscription["subscription_id"]),
        }
        vehicle_snapshot = json.loads(canonical_json(vehicle).decode("utf-8"))
        key = "|".join([
            subscription_snapshot["environment"],
            subscription_snapshot["subscription_id"],
            remote_id,
        ])
        with self._visual_render_guard:
            # Mesmo estado visual já solicitado/concluído não ocupa a fila.
            if self._visual_render_signature.get(key) == signature:
                return False
            generation = int(self._visual_render_generation.get(key, 0)) + 1
            self._visual_render_generation[key] = generation
            self._visual_render_signature[key] = signature
            self._visual_jobs_pending += 1
        try:
            pool.submit(
                self._render_visual_background,
                subscription_snapshot,
                vehicle_snapshot,
                str(source_at or utc_iso()),
                str(state or "parked"),
                bool(interactive),
                key,
                generation,
                signature,
            )
        except RuntimeError:
            with self._visual_render_guard:
                self._visual_jobs_pending = max(0, self._visual_jobs_pending - 1)
                if self._visual_render_generation.get(key) == generation:
                    self._visual_render_signature.pop(key, None)
            return False
        return True

    def _render_visual_background(
        self,
        subscription_snapshot: dict[str, Any],
        vehicle_snapshot: dict[str, Any],
        source_at: str,
        state: str,
        interactive: bool,
        key: str,
        generation: int,
        signature: str,
    ) -> None:
        """Render from local ZIP only; stale visual generations are discarded."""
        started = time.monotonic()
        try:
            with self._visual_render_guard:
                if self._visual_render_generation.get(key) != generation:
                    return
            rendered = connector.render_official_visual_snapshot(vehicle_snapshot)
            if rendered is None:
                with self._visual_render_guard:
                    if self._visual_render_generation.get(key) == generation:
                        self._visual_render_signature.pop(key, None)
                return
            with self._visual_render_guard:
                if (
                    self._visual_render_generation.get(key) != generation
                    or self._visual_render_signature.get(key) != signature
                ):
                    return
            queued = self._queue_event(
                subscription_snapshot,
                rendered,
                source_at,
                state,
                interactive=interactive,
                force_delivery=False,
            )
            elapsed_ms = int(round((time.monotonic() - started) * 1000))
            if elapsed_ms >= 250:
                LOG.info(
                    "Imagem local de %s renderizada fora da conta em %sms; evento_visual=%s.",
                    str(vehicle_snapshot.get("remote_id") or "")[:32],
                    elapsed_ms,
                    bool(queued.get("queued")),
                )
        except Exception as exc:  # noqa: BLE001
            with self._visual_render_guard:
                if self._visual_render_generation.get(key) == generation:
                    self._visual_render_signature.pop(key, None)
            LOG.warning(
                "Render visual local falhou sem afetar telemetria/controle: %s",
                connector.clean_message(str(exc)),
            )
        finally:
            with self._visual_render_guard:
                self._visual_jobs_pending = max(0, self._visual_jobs_pending - 1)
            self.delivery_event.set()

    def _session_operation_lock(self, subscription_id: str) -> threading.RLock:
        key = str(subscription_id or "").strip()
        with self.session_locks_guard:
            lock = self.session_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self.session_locks[key] = lock
            return lock

    def _collect_with_session(
        self,
        subscription_id: str,
        environment: str,
        account_id: int,
        credentials: dict[str, Any],
        vehicle_ids: set[str],
        command_mode: bool = False,
        manual_should_yield: Callable[[], bool] | None = None,
        allow_slow_network: bool = True,
    ) -> dict[str, Any]:
        # Somente a sessão desta conta fica bloqueada durante a chamada de rede.
        # Outras contas respeitam o limite global do Connector, mas não ficam
        # paradas atrás de uma autenticação lenta ou de um veículo offline.
        session_lock_started = time.monotonic()
        with self._session_operation_lock(subscription_id):
            log_slow_telemetry_stage(subscription_id, "session_operation_lock_wait", session_lock_started)
            return self._collect_with_session_locked(
                subscription_id,
                environment,
                account_id,
                credentials,
                vehicle_ids,
                command_mode=command_mode,
                manual_should_yield=manual_should_yield,
                allow_slow_network=allow_slow_network,
            )

    def _telemetry_vehicle_list_one_shot(
        self,
        subscription_id: str,
        client: Any,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> list[Any]:
        """Read the vehicle list without leapmotor-api's hidden auth retry chain.

        1.12.89 — field logs from 1.12.88 proved the remaining long account
        hold was before status: a confirmation poll could enter the public
        ``get_vehicle_list()`` wrapper, which may perform status/list -> token
        refresh -> full login -> retry while the account lock remains held.
        Only the pinned private request is used here. A token-expiry path gets
        at most one refresh and one second list request, with manual priority
        checked between every network step. No full login occurs inside this
        helper and no second client is created.
        """

        def yield_for_manual(moment: str) -> None:
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual(
                    f"Operação manual recebeu prioridade {moment} da lista de veículos."
                )

        yield_for_manual("antes")

        if hasattr(client, "token") and not getattr(client, "token", None):
            self._close_session_locked(subscription_id)
            raise connector.ConnectorSessionExpiredError(
                "Sessão Leapmotor sem token antes da lista; nova autenticação ficará para o próximo ciclo protegido."
            )

        method = getattr(client, "_get_vehicle_list", None)
        if not callable(method):
            raise connector.ConnectorTemporaryError(
                "A versão fixada de leapmotor-api não expõe _get_vehicle_list; "
                "a telemetria recusou fallback para retry invisível."
            )

        def call_once() -> list[Any]:
            request_started = time.monotonic()
            try:
                with self._telemetry_request_timeout(client):
                    value = method()
            finally:
                log_slow_telemetry_stage(subscription_id, "vehicle_list_request", request_started)
            return value if isinstance(value, list) else list(value or [])

        try:
            value = call_once()
        except Exception as exc:  # noqa: BLE001
            yield_for_manual("depois da primeira tentativa")
            if not connector.is_session_expired_error(exc):
                raise

            yield_for_manual("antes do refresh")
            refresh_started = time.monotonic()
            try:
                with self._telemetry_request_timeout(client):
                    refreshed = self._try_refresh_client_session(client)
            finally:
                log_slow_telemetry_stage(subscription_id, "vehicle_list_refresh", refresh_started)
            yield_for_manual("depois do refresh")

            if not refreshed:
                self._close_session_locked(subscription_id)
                raise connector.ConnectorSessionExpiredError(
                    "Refresh único não recuperou a lista; a reconexão ficará para o próximo ciclo protegido."
                ) from exc

            LOG.info(
                "Sessão de %s renovada por refresh cooperativo durante lista de veículos; "
                "uma única releitura será feita se não houver comando manual.",
                subscription_id,
            )

            yield_for_manual("antes da releitura")
            try:
                value = call_once()
            except Exception as retry_exc:  # noqa: BLE001
                yield_for_manual("depois da releitura")
                if connector.is_session_expired_error(retry_exc):
                    self._close_session_locked(subscription_id)
                    raise connector.ConnectorSessionExpiredError(
                        "Lista continuou com sessão expirada após um refresh e uma releitura; "
                        "não haverá terceira chamada neste ciclo."
                    ) from retry_exc
                raise

        yield_for_manual("depois")
        return value

    def _telemetry_message_list_one_shot(
        self,
        subscription_id: str,
        client: Any,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> Any:
        """Read one message page without the public hidden token retry chain.

        Messages run only on the slow background profile, but a manual command
        may arrive while that call already owns the account. 1.12.89 applies
        the same bounded cooperative rule as vehicle list/status so no automatic
        read can hide refresh+login+retry behind one public library method.
        """

        def yield_for_manual(moment: str) -> None:
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual(
                    f"Operação manual recebeu prioridade {moment} da leitura de mensagens."
                )

        yield_for_manual("antes")

        if hasattr(client, "token") and not getattr(client, "token", None):
            self._close_session_locked(subscription_id)
            raise connector.ConnectorSessionExpiredError(
                "Sessão Leapmotor sem token antes das mensagens; nova autenticação ficará para o próximo ciclo protegido."
            )

        method = getattr(client, "_get_message_list", None)
        if not callable(method):
            raise connector.ConnectorTemporaryError(
                "A versão fixada de leapmotor-api não expõe _get_message_list; "
                "a telemetria recusou fallback para retry invisível."
            )

        def call_once() -> Any:
            request_started = time.monotonic()
            try:
                with self._telemetry_request_timeout(client):
                    return method(page_no=1, page_size=100)
            finally:
                log_slow_telemetry_stage(subscription_id, "message_list_request", request_started)

        try:
            value = call_once()
        except Exception as exc:  # noqa: BLE001
            yield_for_manual("depois da primeira tentativa")
            if not connector.is_session_expired_error(exc):
                raise

            yield_for_manual("antes do refresh")
            refresh_started = time.monotonic()
            try:
                with self._telemetry_request_timeout(client):
                    refreshed = self._try_refresh_client_session(client)
            finally:
                log_slow_telemetry_stage(subscription_id, "message_list_refresh", refresh_started)
            yield_for_manual("depois do refresh")

            if not refreshed:
                self._close_session_locked(subscription_id)
                raise connector.ConnectorSessionExpiredError(
                    "Refresh único não recuperou mensagens; a reconexão ficará para o próximo ciclo protegido."
                ) from exc

            LOG.info(
                "Sessão de %s renovada por refresh durante a leitura de mensagens (cooperativo); "
                "uma única releitura será feita se não houver comando manual.",
                subscription_id,
            )

            yield_for_manual("antes da releitura")
            try:
                value = call_once()
            except Exception as retry_exc:  # noqa: BLE001
                yield_for_manual("depois da releitura")
                if connector.is_session_expired_error(retry_exc):
                    self._close_session_locked(subscription_id)
                    raise connector.ConnectorSessionExpiredError(
                        "Mensagens continuaram com sessão expirada após um refresh e uma releitura; "
                        "não haverá terceira chamada neste ciclo."
                    ) from retry_exc
                raise

        yield_for_manual("depois")
        return value

    def _telemetry_status_one_shot(
        self,
        subscription_id: str,
        client: Any,
        vehicle: Any,
        manual_should_yield: Callable[[], bool] | None = None,
    ) -> Any:
        # 1.12.88 — leitura de status cooperativa sem retry invisível.
        # O mesmo LeapmotorApiClient persistente continua protegido pelas
        # travas existentes. Não há segundo cliente nem uso concorrente.

        def yield_for_manual(moment: str) -> None:
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual(
                    f"Operação manual recebeu prioridade {moment} da leitura de status."
                )

        yield_for_manual("antes")

        if hasattr(client, "token") and not getattr(client, "token", None):
            self._close_session_locked(subscription_id)
            raise connector.ConnectorSessionExpiredError(
                "Sessão Leapmotor sem token; nova autenticação será feita no próximo ciclo protegido."
            )

        method = getattr(client, "_get_vehicle_status", None)
        if not callable(method):
            raise connector.ConnectorTemporaryError(
                "A versão fixada de leapmotor-api não expõe _get_vehicle_status; "
                "a telemetria recusou fallback para retry invisível."
            )

        def call_once() -> Any:
            request_started = time.monotonic()
            try:
                with self._telemetry_request_timeout(client):
                    return method(vehicle)
            finally:
                log_slow_telemetry_stage(subscription_id, "status_request", request_started)

        try:
            value = call_once()
        except Exception as exc:  # noqa: BLE001
            yield_for_manual("depois da primeira tentativa")
            if not connector.is_session_expired_error(exc):
                raise

            yield_for_manual("antes do refresh")
            refresh_started = time.monotonic()
            try:
                with self._telemetry_request_timeout(client):
                    refreshed = self._try_refresh_client_session(client)
            finally:
                log_slow_telemetry_stage(subscription_id, "status_refresh", refresh_started)
            yield_for_manual("depois do refresh")

            if not refreshed:
                self._close_session_locked(subscription_id)
                raise connector.ConnectorSessionExpiredError(
                    "Refresh único não recuperou a sessão; a reconexão ficará para o próximo ciclo protegido."
                ) from exc

            LOG.info(
                "Sessão de %s renovada por refresh cooperativo durante status; "
                "uma única releitura será feita se não houver comando manual.",
                subscription_id,
            )

            yield_for_manual("antes da releitura")
            try:
                value = call_once()
            except Exception as retry_exc:  # noqa: BLE001
                yield_for_manual("depois da releitura")
                if connector.is_session_expired_error(retry_exc):
                    self._close_session_locked(subscription_id)
                    raise connector.ConnectorSessionExpiredError(
                        "Sessão continuou expirada após um refresh e uma releitura; "
                        "não haverá terceira chamada neste ciclo."
                    ) from retry_exc
                raise

        yield_for_manual("depois")
        return value

    def _collect_with_session_locked(
        self,
        subscription_id: str,
        environment: str,
        account_id: int,
        credentials: dict[str, Any],
        vehicle_ids: set[str],
        command_mode: bool = False,
        manual_should_yield: Callable[[], bool] | None = None,
        allow_slow_network: bool = True,
    ) -> dict[str, Any]:
        now_epoch = time.time()
        credential_hash = hashlib.sha256(canonical_json(credentials)).hexdigest()
        with self.session_lock:
            session = self.sessions.get(subscription_id)
        if session is not None and (
            session.get("credential_hash") != credential_hash
            or (self.session_max_age_seconds > 0 and now_epoch - float(session.get("created_at") or 0) >= self.session_max_age_seconds)
            or (self.session_idle_seconds > 0 and now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds)
        ):
            self._close_session_locked(subscription_id)
            session = None

        if session is None:
            # Verifique a prioridade manual antes de criar uma nova sessão e
            # novamente imediatamente antes do login. Isso fecha a corrida em
            # que a telemetria iniciava a autenticação no mesmo instante em que
            # o usuário enviava um comando.
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando antes da autenticação automática.")
            session = self._create_persistent_session_locked(
                subscription_id,
                environment,
                account_id,
                credentials,
                "telemetry",
                manual_should_yield=manual_should_yield,
            )

        client = session["client"]
        try:
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            cached_vehicles = session.get("vehicles") if isinstance(session.get("vehicles"), list) else []
            vehicles_cached_at = float(session.get("vehicles_cached_at") or 0)
            cache_fresh = bool(cached_vehicles) and now_epoch - vehicles_cached_at < self.vehicle_list_cache_seconds
            selected_ids_present = not vehicle_ids or all(
                any(
                    str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "")) == vehicle_id
                    for item in cached_vehicles
                )
                for vehicle_id in vehicle_ids
            )
            if cache_fresh and selected_ids_present:
                vehicles = cached_vehicles
            else:
                private_vehicle_list = getattr(client, "_get_vehicle_list", None)
                client_module = str(getattr(type(client), "__module__", "") or "")
                official_leapmotor_client = (
                    client_module == "leapmotor_api"
                    or client_module.startswith("leapmotor_api.")
                )
                if callable(private_vehicle_list):
                    vehicles = self._telemetry_vehicle_list_one_shot(
                        subscription_id,
                        client,
                        manual_should_yield=manual_should_yield,
                    )
                elif official_leapmotor_client:
                    raise connector.ConnectorTemporaryError(
                        "Cliente Leapmotor real sem _get_vehicle_list; "
                        "telemetria recusou fallback para retry invisível."
                    )
                else:
                    # Compatibilidade apenas com fakes/contratos históricos.
                    # Cliente real da biblioteca pinada nunca passa por este ramo.
                    with self._telemetry_request_timeout(client):
                        vehicles_value = client.get_vehicle_list()
                    vehicles = vehicles_value if isinstance(vehicles_value, list) else list(vehicles_value or [])
                session["vehicles"] = vehicles
                session["vehicles_cached_at"] = time.time()
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            selected = vehicles
            if vehicle_ids:
                selected = [
                    item for item in vehicles
                    if str(connector.attribute(item, "car_id", "") or connector.attribute(item, "vin", "")) in vehicle_ids
                ]
            messages: list[Any] = []
            slow_last_at = float(session.get("slow_last_at") or 0)
            slow_cycle = (
                allow_slow_network
                and not command_mode
                and ORCHESTRATOR.secondary_network_allowed(environment, account_id)
                and now_epoch - slow_last_at >= self.slow_interval_seconds
            )
            get_messages = getattr(client, "get_message_list", None)
            if manual_should_yield is not None and manual_should_yield():
                raise TelemetryYieldForManual("Operação manual aguardando a conta.")
            if slow_cycle and callable(get_messages):
                cached_messages = session.get("messages") if isinstance(session.get("messages"), list) else []
                messages_cached_at = float(session.get("messages_cached_at") or 0)
                if messages_cached_at > 0 and now_epoch - messages_cached_at < self.message_cache_seconds:
                    messages = cached_messages
                else:
                    if manual_should_yield is not None and manual_should_yield():
                        raise TelemetryYieldForManual("Operação manual aguardando a conta.")
                    private_message_list = getattr(client, "_get_message_list", None)
                    client_module = str(getattr(type(client), "__module__", "") or "")
                    official_leapmotor_client = (
                        client_module == "leapmotor_api"
                        or client_module.startswith("leapmotor_api.")
                    )
                    try:
                        if callable(private_message_list):
                            message_page = self._telemetry_message_list_one_shot(
                                subscription_id,
                                client,
                                manual_should_yield=manual_should_yield,
                            )
                        elif official_leapmotor_client:
                            raise connector.ConnectorTemporaryError(
                                "Cliente Leapmotor real sem _get_message_list; "
                                "telemetria recusou fallback para retry invisível."
                            )
                        else:
                            # Compatibilidade apenas com clientes sintéticos dos testes.
                            with self._telemetry_request_timeout(client):
                                message_page = get_messages(page_no=1, page_size=100)
                        messages = list(connector.attribute(message_page, "messages", []) or [])
                        session["messages"] = messages
                        session["messages_cached_at"] = time.time()
                    except TelemetryYieldForManual:
                        raise
                    except Exception:
                        # Mensagens são enriquecimento SLOW. Uma falha não derruba
                        # status/controles nem autoriza outra sequência de retry.
                        messages = cached_messages
            serialized: list[dict[str, Any]] = []
            for item in selected:
                if manual_should_yield is not None and manual_should_yield():
                    raise TelemetryYieldForManual("Operação manual aguardando a conta.")
                try:
                    private_status = getattr(client, "_get_vehicle_status", None)
                    client_module = str(getattr(type(client), "__module__", "") or "")
                    official_leapmotor_client = (
                        client_module == "leapmotor_api"
                        or client_module.startswith("leapmotor_api.")
                    )

                    if callable(private_status):
                        status_value = self._telemetry_status_one_shot(
                            subscription_id,
                            client,
                            item,
                            manual_should_yield=manual_should_yield,
                        )
                        serialize_started = time.monotonic()
                        try:
                            serialized_item = connector.serialize_vehicle(
                                item,
                                include_status=True,
                                client=client,
                                messages=messages,
                                allow_unscoped_messages=len(selected) == 1,
                                manual_should_yield=manual_should_yield,
                                include_secondary_network=False,
                                status_override=status_value,
                                include_official_image=False,
                            )
                        finally:
                            log_slow_telemetry_stage(subscription_id, "serialize_vehicle", serialize_started)
                    elif official_leapmotor_client:
                        raise connector.ConnectorTemporaryError(
                            "Cliente Leapmotor real sem _get_vehicle_status; "
                            "telemetria recusou fallback para retry invisivel."
                        )
                    else:
                        serialized_item = connector.serialize_vehicle(
                            item,
                            include_status=True,
                            client=client,
                            messages=messages,
                            allow_unscoped_messages=len(selected) == 1,
                            manual_should_yield=manual_should_yield,
                            include_secondary_network=False,
                            include_official_image=False,
                        )
                except TelemetryYieldForManual:
                    raise
                except Exception as exc:  # noqa: BLE001
                    if manual_should_yield is not None and manual_should_yield():
                        raise TelemetryYieldForManual(
                            "Operação manual recebeu prioridade durante a leitura/serialização de status do veículo."
                        ) from exc
                    raise
                if manual_should_yield is not None and manual_should_yield():
                    raise TelemetryYieldForManual(
                        "Operação manual recebeu prioridade após a leitura de status do veículo."
                    )
                serialized.append(serialized_item)
            if not serialized:
                raise RuntimeError("Nenhum veículo foi encontrado para esta conta.")
            session["last_used_at"] = time.time()
            session["vehicles"] = vehicles
            if slow_cycle:
                session["slow_last_at"] = time.time()
            return {
                "ok": True,
                "account_name": "Conta Leapmotor",
                "vehicles": serialized,
                "connector_version": connector.CONNECTOR_VERSION,
                "library_version": connector.package_version(),
                "session_reused": True,
                "collection_profile": "slow" if slow_cycle else "fast",
            }
        except TelemetryYieldForManual:
            session["last_used_at"] = time.time()
            raise
        except Exception as exc:
            if connector.is_session_expired_error(exc) or isinstance(exc, connector.ConnectorSessionExpiredError):
                self._close_session_locked(subscription_id)
                raise connector.ConnectorSessionExpiredError(
                    "A sessão Leapmotor expirou; o próximo ciclo fará uma única autenticação coordenada."
                ) from exc
            if connector.is_transient_cloud_error(exc) or isinstance(exc, connector.ConnectorTemporaryError):
                # Um timeout de transporte não prova que o token morreu. A
                # sessão é mantida nas primeiras falhas para evitar novo login.
                session["last_used_at"] = time.time()
                raise
            self._close_session_locked(subscription_id)
            raise

    def _close_session_locked(self, subscription_id: str) -> None:
        with self.session_lock:
            session = self.sessions.pop(str(subscription_id), None)
        if not session:
            return
        client = session.get("client")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        temp_dir = session.get("temp_dir")
        if temp_dir:
            shutil.rmtree(Path(temp_dir), ignore_errors=True)

    def _close_session(self, subscription_id: str) -> None:
        with self._session_operation_lock(subscription_id):
            self._close_session_locked(subscription_id)

    def _close_all_sessions(self) -> None:
        with self.session_lock:
            subscription_ids = list(self.sessions)
        for subscription_id in subscription_ids:
            self._close_session(subscription_id)

    def _has_session(self, subscription_id: str) -> bool:
        with self.session_lock:
            return str(subscription_id) in self.sessions

    def _mark_auth_required(self, subscription_id: str, message: str) -> None:
        now = utc_iso()
        with self.schedule_lock, self._db(timeout_seconds=2.0) as db:
            db.execute(
                "UPDATE subscriptions SET status='auth_required', auth_required=1, active_until=0, interactive_until=0, command_until=0, command_key=NULL, command_vehicle_id=NULL, command_context_json=NULL, command_poll_count=0, command_started_at=0, next_run_at=?, last_run_at=?, last_error=?, consecutive_failures=consecutive_failures+1, updated_at=? WHERE subscription_id=?",
                (time.time() + 86400, now, str(message or "")[:500], now, subscription_id),
            )

    @staticmethod
    def _transient_backoff(failures: int, interactive: bool, command_mode: bool = False) -> int:
        # A espera de comando tem prazo curto e cadência própria; ela não pode
        # herdar o backoff de quem só está olhando a tela.
        if command_mode:
            schedule = TelemetryEngine.COMMAND_TRANSIENT_BACKOFF
        else:
            schedule = (45, 90, 180, 300, 900, 1800) if interactive else (120, 300, 900, 1800, 3600, 10800)
        return schedule[min(max(1, int(failures)), len(schedule)) - 1]

    def _within_command_window(self, delay: int, command_until: float, now_epoch: float) -> int:
        """Encurta um reagendamento que cairia depois do fim da janela.

        Sem isto, qualquer atraso escolhido por outro motivo (falha temporária,
        conta ocupada, backoff de erro) desperdiça o que resta da janela: a
        leitura seguinte chega quando a espera já foi encerrada por prazo. O
        piso de 2s existe para não transformar o encurtamento em laço apertado
        contra a nuvem.
        """
        remaining = float(command_until or 0) - float(now_epoch)
        if remaining <= 0:
            return int(delay)
        return max(2, min(int(delay), int(remaining) - self.COMMAND_WINDOW_MIN_MARGIN_SECONDS))

    @staticmethod
    def _failure_backoff(failures: int) -> int:
        schedule = (300, 900, 1800, 3600, 10800, 21600)
        return schedule[min(max(1, int(failures)), len(schedule)) - 1]

    def _state_of(self, telemetry: dict[str, Any]) -> str:
        state = str(telemetry.get("vehicle_state") or "").lower()
        charging = str(telemetry.get("charging_status") or "").lower()
        try:
            speed = float(telemetry.get("speed_kmh") or 0)
        except (TypeError, ValueError):
            speed = 0
        if charging in {"charging", "active", "fast_charging", "slow_charging", "dc_charging", "ac_charging"} or state == "charging":
            return "charging"
        # READY/ignição isolados variam mesmo com o carro parado em alguns
        # firmwares. Só velocidade real ou estado driving não contradito por
        # is_parked confirmam condução.
        if speed > 1 or (state == "driving" and telemetry.get("is_parked") is not True):
            return "driving"
        if telemetry.get("plugged") is True or charging == "plugged":
            return "charge_watch"
        if (
            telemetry.get("is_parked") is True
            or state in {"parked", "locked", "off", "ready"}
            or telemetry.get("ready_state") is True
            or telemetry.get("ignition_on") is True
        ):
            return "parked"
        return "sleep"

    # 1.12.65 — quem já teve atividade observada, por assinatura. Em memória de
    # propósito: reiniciar o App custa um ciclo rápido a mais, nunca um lento.
    _ACTIVITY_REGISTRY: dict[str, str] = {}

    @staticmethod
    def activity_fingerprint(telemetry: dict[str, Any]) -> str:
        """O que muda quando alguém mexe no carro: aberturas e tranca.

        Bateria, autonomia e temperatura oscilam com o carro dormindo e não
        provam nada. Porta, porta-malas, capô, vidros, cortina e trava, sim.
        """
        doors = telemetry.get("doors") if isinstance(telemetry.get("doors"), dict) else {}
        parts = [f"{name}={doors.get(name)!r}" for name in sorted(doors)]
        for key in ("locked", "windows", "sunshade_open", "hood_open", "plugged"):
            parts.append(f"{key}={telemetry.get(key)!r}")
        return "|".join(parts)

    @staticmethod
    def parked_streak_after_activity(previous_streak: int, activity_changed: bool) -> int:
        """Mexer no carro prova que ele está acordado: a contagem recomeça.

        Sem isto, `_adaptive_interval` rebaixa parado para `sleep_seconds` na
        sexta leitura — sete minutos e meio de relógio, sem nunca perguntar ao
        carro. Foi o defeito relatado em 01/08/2026: o porta-malas aberto com o
        carro parado havia mais tempo que isso esperava a leitura lenta.
        """
        return 0 if activity_changed else max(0, int(previous_streak or 0))

    @staticmethod
    def _confirm_state_transition(
        previous_state: str, candidate_state: str, candidate_count: int, observed_state: str
    ) -> tuple[str, str, int]:
        previous = str(previous_state or "").lower()
        observed = str(observed_state or "sleep").lower()
        if not previous:
            return observed, "", 0
        if observed == previous:
            return previous, "", 0
        required = 1 if observed == "charging" else 3 if observed == "sleep" else 2
        count = int(candidate_count or 0) + 1 if str(candidate_state or "") == observed else 1
        if count >= required:
            return observed, "", 0
        return previous, observed, count

    def _adaptive_interval(
        self,
        states: list[str],
        previous_parked_streak: int,
        interactive: bool = False,
        command_mode: bool = False,
        command_poll_count: int = 0,
    ) -> tuple[int, str, int]:
        if command_mode:
            if "driving" in states:
                aggregate = "driving"
            elif "charging" in states:
                aggregate = "charging"
            elif "charge_watch" in states:
                aggregate = "charge_watch"
            elif "parked" in states:
                aggregate = "parked"
            else:
                aggregate = "sleep"
            streak = 0 if aggregate in {"driving", "charging"} else previous_parked_streak + 1
            cadence_index = min(max(1, int(command_poll_count)) - 1, len(self.command_cadence) - 1)
            return int(self.command_cadence[cadence_index]), aggregate, streak
        if interactive:
            if "driving" in states:
                return min(self.active_seconds, self.interactive_seconds), "driving", 0
            if "charging" in states:
                return min(self.charging_seconds, self.interactive_seconds), "charging", 0
            if "charge_watch" in states:
                return self.interactive_seconds, "charge_watch", 0
            if "parked" in states:
                return self.interactive_seconds, "parked", previous_parked_streak + 1
            return self.interactive_seconds, "sleep", previous_parked_streak + 1
        if "driving" in states:
            return self.active_seconds, "driving", 0
        if "charging" in states:
            return self.charging_seconds, "charging", 0
        if "charge_watch" in states:
            return self.charge_watch_seconds, "charge_watch", 0
        if "parked" in states:
            streak = previous_parked_streak + 1
            if streak >= 6:
                return self.sleep_seconds, "sleep", streak
            return self.parked_seconds, "parked", streak
        return self.sleep_seconds, "sleep", previous_parked_streak + 1

    @staticmethod
    def _command_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "open", "opened", "active", "running", "charging"}:
            return True
        if normalized in {"0", "false", "no", "off", "closed", "close", "inactive", "stopped", "idle", "not_charging"}:
            return False
        return None

    # 1.12.61 — o relógio da nuvem chega ligeiramente adiantado em relação ao do
    # gateway (medido em ~1 min em 30/07/2026). Uma amostra pouco à frente é
    # normal e continua servindo; muito à frente não. O teto existe como guarda
    # contra interpretar o fuso na direção errada: se algum dia o carimbo vier
    # mesmo em UTC, presumi-lo local jogaria a amostra ~3h no futuro, e é melhor
    # não confirmar nada do que confirmar com carimbo impossível.
    COMMAND_SAMPLE_FUTURE_TOLERANCE_SECONDS = 900.0

    @staticmethod
    def _command_sample_epoch(telemetry: dict[str, Any]) -> float | None:
        """Epoch da captura da amostra, com o fuso resolvido em um lugar só.

        `captured_at` chega **sem fuso** quando a nuvem informa `collectTime`: a
        `leapmotor_api` faz `datetime.strptime` (ingênuo, com `noqa: DTZ007`) e o
        connector serializa com `isoformat()`. Presumir UTC nesse caso desloca o
        carimbo pelo offset do host.

        Isso foi medido em produção em 30/07/2026, num host em -03:00: três
        comandos consecutivos relataram a amostra 10739s, 10740s e 10777s antes do
        envio, com o carro respondendo e a cortina do teto abrindo e fechando de
        fato. Que era deslocamento fixo e não atraso real ficou provado pelos três
        valores **não** crescerem com os 2 min de intervalo entre os comandos —
        atraso real cresceria. O site já lia o mesmo campo como hora local (via
        `strtotime`) e exibia a idade correta; só esta comparação divergia.

        Por isso, sem fuso = hora local. Frescura e atraso passam a derivar deste
        único ponto para não poderem discordar entre si.
        """
        raw = telemetry.get("captured_at")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            # `astimezone()` num datetime ingênuo assume hora local e anexa o
            # offset do host, que é o que o carimbo da nuvem representa.
            parsed = parsed.astimezone()
        try:
            return parsed.timestamp()
        except (OverflowError, OSError, ValueError):
            return None

    @classmethod
    def _command_sample_lag(cls, telemetry: dict[str, Any], command_started_at: float) -> float | None:
        """Distância em segundos entre a captura da amostra e o envio do comando.

        Positivo = o carro não subiu nada novo depois do comando. É a diferença
        entre "o carro recebeu e não obedeceu" e "o carro não reportou", que o
        contador de amostras descartadas sozinho não conseguia expressar.

        `None` quando não há como comparar: sem carimbo de hora na amostra ou
        sem hora de envio registrada. Nesses casos a frescura é presumida (ver
        `_command_sample_is_fresh`), então não há atraso a relatar.
        """
        if command_started_at <= 0:
            return None
        captured = cls._command_sample_epoch(telemetry)
        if captured is None:
            return None
        return command_started_at - captured

    @classmethod
    def _command_sample_is_fresh(cls, telemetry: dict[str, Any], command_started_at: float) -> bool:
        if command_started_at <= 0:
            return True
        lag = cls._command_sample_lag(telemetry, command_started_at)
        if lag is None:
            # Sem carimbo comparável a frescura é presumida, como antes: é melhor
            # avaliar a amostra do que descartar toda confirmação por falta de hora.
            return True
        if lag < -cls.COMMAND_SAMPLE_FUTURE_TOLERANCE_SECONDS:
            return False
        return lag <= 2.0

    # 1.12.56 — os campos que `_command_confirmation` consulta, por comando.
    # Comandos confirmados executam e o dono vê "não foi confirmado dentro da
    # janela segura": o matcher devolve inconclusivo quando o campo esperado
    # não vem na telemetria, e não havia como saber qual campo faltou. Um
    # contrato garante que este mapa cobre todo comando tratado no matcher.
    COMMAND_CONFIRMATION_FIELDS: dict[str, tuple[str, ...]] = {
        "lock": ("locked",),
        "unlock": ("locked",),
        # 1.12.90 — ligar/desligar continua exigindo o switch, mas modos
        # específicos também precisam dos detalhes do HVAC. `climate_details`
        # é um objeto porque diferentes modelos/firmwares podem preencher
        # `mode`, `operate_mode` ou `cooling_and_heating`.
        "climate_on": ("climate_on", "climate_details"),
        "climate_off": ("climate_on",),
        "quick_cool": ("climate_on", "climate_details"),
        "quick_heat": ("climate_on", "climate_details"),
        "windshield_defrost": ("climate_details.windshield_defrost",),
        "prepare_car": ("climate_on", "climate_details"),
        "battery_preheat_on": ("climate_details.battery_preheat",),
        "battery_preheat_off": ("climate_details.battery_preheat",),
        "steering_wheel_heat_on": ("seat_comfort.steering_wheel_heating",),
        "steering_wheel_heat_off": ("seat_comfort.steering_wheel_heating",),
        "rearview_mirror_heat_on": ("mirrors.left_heating", "mirrors.right_heating"),
        "rearview_mirror_heat_off": ("mirrors.left_heating", "mirrors.right_heating"),
        "trunk_open": ("doors.trunk",),
        "trunk_close": ("doors.trunk",),
        "sunshade_open": ("sunshade_open",),
        "sunshade_close": ("sunshade_open",),
        "sunshade_position": ("sunshade_percent",),
        "windows_open": ("windows",),
        "windows_close": ("windows",),
        "windows_position": ("window_positions",),
        "sentry_on": ("security.sentry_mode", "sentry_mode"),
        "sentry_off": ("security.sentry_mode", "sentry_mode"),
        "start_charging": ("charging_status", "charging_power_kw"),
        "stop_charging": ("charging_status", "charging_power_kw"),
        "set_charge_limit": ("charge_limit_percent",),
    }

    def _command_confirmation_gaps(self, command_key: str, telemetry: dict[str, Any]) -> list[str]:
        """Classifica cada campo exigido pelo matcher: ausente, nulo ou vazio.

        Só nomes de campo e classificação saem daqui. Nenhum valor de
        telemetria é registrado — a mesma leitura carrega localização e
        identificadores do veículo.
        """
        command = str(command_key or "").strip().lower()
        gaps: list[str] = []
        for path in self.COMMAND_CONFIRMATION_FIELDS.get(command, ()):  # desconhecido -> sem campo exigido
            node: Any = telemetry
            missing = False
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    missing = True
                    break
                node = node[part]
            if missing:
                gaps.append(path + "=ausente")
            elif node is None:
                gaps.append(path + "=nulo")
            elif isinstance(node, dict) and not node:
                gaps.append(path + "=vazio")
        return gaps

    @classmethod
    def _command_climate_mode(cls, telemetry: dict[str, Any]) -> tuple[str | None, bool]:
        """Normaliza o modo físico do HVAC sem assumir um modelo específico.

        OFF é comprovado pelo switch. Para AUTO/COOL/HEAT, a confirmação exige
        um sinal explícito de modo. Valores conhecidos do C10 (0/1/3) são
        aceitos, mas também há fallback textual para B10 e modelos futuros.
        Se o veículo não publicar um modo reconhecível, a resposta é
        inconclusiva — nunca confirma HEAT apenas porque o ar está ligado.
        """
        switch_state = cls._command_bool(telemetry.get("climate_on"))
        if switch_state is False:
            return "off", True
        if switch_state is not True:
            return None, False

        details = telemetry.get("climate_details")
        if not isinstance(details, dict):
            return None, False

        numeric_map = {0: "auto", 1: "cooling", 3: "heating"}
        for key in ("mode",):
            raw = details.get(key)
            if raw is None:
                continue
            try:
                number = int(float(str(raw).strip()))
            except (TypeError, ValueError):
                number = None
            if number in numeric_map:
                return numeric_map[number], True

        tokens: list[str] = []
        for key in ("mode", "operate_mode", "cooling_and_heating"):
            raw = details.get(key)
            if raw is None:
                continue
            if isinstance(raw, dict):
                for nested in ("value", "name", "label", "description"):
                    value = raw.get(nested)
                    if value is not None:
                        tokens.append(str(value).strip().lower())
            else:
                tokens.append(str(raw).strip().lower())

        text = " ".join(token for token in tokens if token)
        # AUTO precisa ser testado antes de "hot"/"cold": o valor conhecido
        # `nohotcold` contém ambas as palavras e não pode virar HEAT/COOL por
        # simples substring.
        if any(token in text for token in ("nohotcold", "neutral", "auto", "automatic", "wind")):
            return "auto", True
        if any(token in text for token in ("cooling", "quick_cool", "quick cool", "cold", "cool")):
            return "cooling", True
        if any(token in text for token in ("heating", "quick_heat", "quick heat", "hot", "heat")):
            return "heating", True
        if any(token in text for token in ("off", "closed", "close", "disabled")):
            return "off", True
        return None, False

    def _command_confirmation(
        self,
        command_key: str,
        telemetry: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[bool, bool]:
        command = str(command_key or "").strip().lower()
        parameters = context.get("parameters") if isinstance(context.get("parameters"), dict) else {}
        if command in {"lock", "unlock"}:
            state = self._command_bool(telemetry.get("locked"))
            return (state is (command == "lock"), state is not None)
        if command == "climate_off":
            state = self._command_bool(telemetry.get("climate_on"))
            return (state is False, state is not None)
        if command in {"climate_on", "quick_cool", "quick_heat"}:
            # 1.12.90 — `climate_on=true` prova somente que o HVAC está ligado.
            # Não prova AUTO, COOL ou HEAT. Isso evitou um falso positivo de campo
            # onde `quick_heat` foi dado como confirmado enquanto o app oficial
            # ainda mostrava resfriamento.
            mode, evaluable = self._command_climate_mode(telemetry)
            if not evaluable:
                return False, False
            expected_mode = {
                "climate_on": "auto",
                "quick_cool": "cooling",
                "quick_heat": "heating",
            }[command]
            return mode == expected_mode, True
        if command == "windshield_defrost":
            details = telemetry.get("climate_details") if isinstance(telemetry.get("climate_details"), dict) else {}
            state = self._command_bool(details.get("windshield_defrost"))
            parameters = context.get("parameters") if isinstance(context.get("parameters"), dict) else {}
            expected = parameters.get("enabled", True)
            if not isinstance(expected, bool):
                return False, False
            return (state is expected, state is not None)
        if command == "prepare_car":
            parameters = context.get("parameters") if isinstance(context.get("parameters"), dict) else {}
            climate_on = self._command_bool(telemetry.get("climate_on"))
            if climate_on is not True:
                return (False, climate_on is not None)

            requested_mode = str(parameters.get("climate_mode") or "auto").strip().lower()
            expected_mode = {"auto": "auto", "cold": "cooling", "hot": "heating"}.get(requested_mode)
            if expected_mode is None:
                return False, False
            observed_mode, mode_evaluable = self._command_climate_mode(telemetry)
            if not mode_evaluable:
                return False, False
            if observed_mode != expected_mode:
                return False, True

            details = telemetry.get("climate_details") if isinstance(telemetry.get("climate_details"), dict) else {}

            def _number(value: Any) -> float | None:
                try:
                    if value is None or isinstance(value, bool):
                        return None
                    return float(value)
                except (TypeError, ValueError):
                    return None

            requested_fan = _number(parameters.get("wind_level"))
            observed_fan = _number(details.get("fan_level"))
            if requested_fan is None or observed_fan is None:
                return False, False
            if abs(observed_fan - requested_fan) > 0.1:
                return False, True

            requested_temp = _number(parameters.get("temperature"))
            if requested_temp is None:
                return False, False
            known_temps = [
                value for value in (
                    _number(details.get("left_temperature_c")),
                    _number(details.get("right_temperature_c")),
                )
                if value is not None
            ]
            if not known_temps:
                return False, False
            if any(abs(value - requested_temp) > 0.6 for value in known_temps):
                return False, True
            return True, True
        if command in {"battery_preheat_on", "battery_preheat_off"}:
            details = telemetry.get("climate_details") if isinstance(telemetry.get("climate_details"), dict) else {}
            state = self._command_bool(details.get("battery_preheat"))
            expected = command == "battery_preheat_on"
            return (state is expected, state is not None)
        if command in {"steering_wheel_heat_on", "steering_wheel_heat_off"}:
            seat = telemetry.get("seat_comfort") if isinstance(telemetry.get("seat_comfort"), dict) else {}
            state = self._command_bool(seat.get("steering_wheel_heating"))
            expected = command == "steering_wheel_heat_on"
            return (state is expected, state is not None)
        if command in {"rearview_mirror_heat_on", "rearview_mirror_heat_off"}:
            mirrors = telemetry.get("mirrors") if isinstance(telemetry.get("mirrors"), dict) else {}
            known = [self._command_bool(mirrors.get(key)) for key in ("left_heating", "right_heating") if key in mirrors]
            known = [value for value in known if value is not None]
            if not known:
                return False, False
            active = any(known)
            expected = command == "rearview_mirror_heat_on"
            return (active is expected, True)
        if command in {"trunk_open", "trunk_close"}:
            doors = telemetry.get("doors") if isinstance(telemetry.get("doors"), dict) else {}
            state = self._command_bool(doors.get("trunk"))
            expected = command == "trunk_open"
            return (state is expected, state is not None)
        if command in {"sunshade_open", "sunshade_close"}:
            state = self._command_bool(telemetry.get("sunshade_open"))
            expected = command == "sunshade_open"
            return (state is expected, state is not None)
        if command == "sunshade_position":
            raw_expected = parameters.get("sunshade_position", parameters.get("value"))
            actual = telemetry.get("sunshade_percent")
            try:
                requested = int(raw_expected)
                observed = float(actual)
            except (TypeError, ValueError):
                return False, False
            if requested < 0 or requested > 100 or observed < 0 or observed > 100:
                return False, False
            # Mesma conversão física já homologada no connector: 45 -> degrau 5 -> 50%.
            # Tolerância <0,5 impede que 48% confirme 50% enquanto a cortina passa
            # pelo meio do percurso rumo a 100%. Nenhum retry físico nasce daqui.
            expected = ((requested + 5) // 10) * 10
            matched = abs(observed - expected) < 0.5
            native = (requested + 5) // 10
            # 1.12.99 — cada amostra da confirmação fica visível para a
            # homologação física. Apenas percentuais; nenhum identificador,
            # credencial ou conteúdo bruto da nuvem é registrado.
            LOG.info(
                "SUNSHADE_DIAG event=sample pedido_site=%d%% valor_nativo=%d esperado_telemetria=%d observado=%.3f match=%s source=sunshade_percent",
                requested,
                native,
                expected,
                observed,
                matched,
            )
            return (matched, True)
        if command in {"windows_open", "windows_close", "windows_position"}:
            keys = ("front_left", "front_right", "rear_left", "rear_right")
            positions = (
                telemetry.get("window_positions")
                if isinstance(telemetry.get("window_positions"), dict)
                else {}
            )
            observed: list[float] = []
            positions_complete = True
            for key in keys:
                raw = positions.get(key)
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    positions_complete = False
                    break
                if value < 0 or value > 100:
                    positions_complete = False
                    break
                observed.append(value)

            if command == "windows_position":
                raw_expected = parameters.get("window_position", parameters.get("value"))
                try:
                    expected = float(raw_expected)
                except (TypeError, ValueError):
                    return False, False
                if expected < 0 or expected > 100 or not positions_complete:
                    return False, False
                if expected >= 99:
                    return (all(value >= 90 for value in observed), True)
                if expected <= 1:
                    return (all(value <= 5 for value in observed), True)
                return (all(abs(value - expected) <= 5 for value in observed), True)

            if positions_complete:
                if command == "windows_open":
                    return (all(value >= 90 for value in observed), True)
                return (all(value <= 5 for value in observed), True)

            windows = telemetry.get("windows") if isinstance(telemetry.get("windows"), dict) else {}
            states = [self._command_bool(windows.get(key)) for key in keys]
            if any(value is None for value in states):
                return False, False
            if command == "windows_open":
                return (all(value is True for value in states), True)
            return (all(value is False for value in states), True)
        if command in {"sentry_on", "sentry_off"}:
            security = telemetry.get("security") if isinstance(telemetry.get("security"), dict) else {}
            state = self._command_bool(security.get("sentry_mode", telemetry.get("sentry_mode")))
            expected = command == "sentry_on"
            return (state is expected, state is not None)
        if command in {"start_charging", "stop_charging"}:
            charging = str(telemetry.get("charging_status") or "").strip().lower()
            try:
                power = float(telemetry.get("charging_power_kw") or 0)
            except (TypeError, ValueError):
                power = 0.0
            active = charging in {"charging", "active", "fast_charging", "slow_charging", "dc_charging", "ac_charging", "in_progress"} or power > 0.15
            known = bool(charging) or telemetry.get("charging_power_kw") is not None
            return (active if command == "start_charging" else not active, known)
        if command == "set_charge_limit":
            expected = parameters.get("charge_limit_percent")
            actual = telemetry.get("charge_limit_percent")
            try:
                return abs(float(actual) - float(expected)) <= 1.0, actual is not None and expected is not None
            except (TypeError, ValueError):
                return False, False
        # Localizar, liberar conector e enviar destino não possuem um estado
        # confiável de confirmação na telemetria atual.
        return False, False

    @staticmethod
    def _looks_rate_limited(message: str) -> bool:
        normalized = str(message or "").lower()
        if connector.login_cooldown_seconds(normalized) > 0:
            return False
        return any(token in normalized for token in (
            "429", "too many", "password error limit", "login attempt limit", "rate limit", "rate-limit", "throttle", "temporarily blocked",
            "muitas solicitações", "limite de requisições", "conta bloqueada",
        ))

    def _heartbeat_interval(self, state: str, interactive: bool = False) -> int:
        if interactive:
            return max(30, self.interactive_seconds * 2)
        if state in {"driving", "charging"}:
            return 60
        if state == "charge_watch":
            return 120
        if state == "parked":
            return 300
        return 900

    def _queue_event(
        self,
        subscription: sqlite3.Row,
        vehicle: dict[str, Any],
        source_at: str,
        state: str,
        interactive: bool = False,
        force_delivery: bool = False,
    ) -> dict[str, Any]:
        environment = str(subscription["environment"])
        account_id = int(subscription["account_id"])
        subscription_id = str(subscription["subscription_id"])
        remote_id = str(vehicle.get("remote_id") or "").strip()[:190]
        if not remote_id:
            LOG.warning("Veículo sem remote_id ignorado na assinatura %s.", subscription_id)
            return {"queued": False, "reason": "missing_remote_id"}

        semantic_hash = hashlib.sha256(canonical_json(semantic_snapshot(vehicle))).hexdigest()
        telemetry = vehicle.get("telemetry") if isinstance(vehicle.get("telemetry"), dict) else {}
        visual_fingerprint = str(telemetry.get("visual_fingerprint") or "").strip().lower()
        if len(visual_fingerprint) != 64 or any(char not in "0123456789abcdef" for char in visual_fingerprint):
            visual_fingerprint = ""
        now_epoch = time.time()
        now_iso = utc_iso()
        source_at = str(source_at or now_iso).strip()[:80] or now_iso

        with self._db(timeout_seconds=5.0) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cached = db.execute(
                    "SELECT * FROM vehicle_state_cache WHERE subscription_id=? AND remote_id=?",
                    (subscription_id, remote_id),
                ).fetchone()
                unchanged = cached is not None and str(cached["semantic_hash"] or "") == semantic_hash
                last_queued_at = float(cached["last_queued_at"] or 0) if cached is not None else 0.0
                if (
                    unchanged
                    and not force_delivery
                    and now_epoch - last_queued_at < self._heartbeat_interval(state, interactive=interactive)
                ):
                    db.execute(
                        "UPDATE vehicle_state_cache SET visual_fingerprint=?, last_source_at=?, skipped_unchanged=skipped_unchanged+1, updated_at=? WHERE subscription_id=? AND remote_id=?",
                        (visual_fingerprint or None, source_at, now_iso, subscription_id, remote_id),
                    )
                    db.execute("COMMIT")
                    return {"queued": False, "reason": "unchanged", "sequence": int(cached["sequence"] or 0)}

                sequence = (int(cached["sequence"] or 0) if cached is not None else 0) + 1
                state_changed = not unchanged
                event_kind = "confirmation" if force_delivery else ("change" if state_changed else "heartbeat")
                enriched = json.loads(canonical_json(vehicle).decode("utf-8"))
                enriched_telemetry = enriched.get("telemetry") if isinstance(enriched.get("telemetry"), dict) else {}
                enriched_telemetry["gateway_delivery"] = {
                    "version": 1,
                    "engine_version": ENGINE_VERSION,
                    "sequence": sequence,
                    "state_changed": state_changed,
                    "event_kind": event_kind,
                    "vehicle_state": state,
                    "source_at": source_at,
                    "gateway_collected_at": now_iso,
                    "semantic_hash": semantic_hash[:16],
                }
                enriched["telemetry"] = enriched_telemetry
                payload_bytes = canonical_json(enriched)
                payload_hash = hashlib.sha256(payload_bytes).hexdigest()
                event_id = hashlib.sha256(
                    f"{environment}|{account_id}|{subscription_id}|{remote_id}|{sequence}|{payload_hash}".encode()
                ).hexdigest()
                encrypted = self.fernet.encrypt(payload_bytes)
                db.execute(
                    """
                    INSERT INTO events
                    (event_id, subscription_id, environment, account_id, remote_id, source_at, payload_encrypted, payload_hash,
                     status, attempts, next_attempt_at, last_error, created_at, delivered_at, sequence, semantic_hash, state_changed, event_kind)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, NULL, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        event_id, subscription_id, environment, account_id, remote_id, source_at, encrypted, payload_hash,
                        now_epoch, now_iso, sequence, semantic_hash, 1 if state_changed else 0, event_kind,
                    ),
                )
                db.execute(
                    """
                    INSERT INTO vehicle_state_cache
                    (subscription_id, remote_id, semantic_hash, visual_fingerprint, last_source_at, last_queued_at, sequence, skipped_unchanged, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                    ON CONFLICT(subscription_id, remote_id) DO UPDATE SET
                        semantic_hash=excluded.semantic_hash,
                        visual_fingerprint=excluded.visual_fingerprint,
                        last_source_at=excluded.last_source_at,
                        last_queued_at=excluded.last_queued_at,
                        sequence=excluded.sequence,
                        updated_at=excluded.updated_at
                    """,
                    (subscription_id, remote_id, semantic_hash, visual_fingerprint or None, source_at, now_epoch, sequence, now_iso),
                )
                db.execute("COMMIT")
                return {"queued": True, "sequence": sequence, "event_kind": event_kind, "state_changed": state_changed}
            except Exception:
                db.execute("ROLLBACK")
                raise

    def _deliver_due(self) -> bool:
        with self.lock, self._db() as db:
            rows = db.execute(
                """
                SELECT e.*
                FROM events e
                WHERE e.status='pending' AND e.next_attempt_at<=?
                  AND NOT EXISTS (
                      SELECT 1 FROM events older
                      WHERE older.status='pending'
                        AND older.subscription_id=e.subscription_id
                        AND older.remote_id=e.remote_id
                        AND (
                            (older.sequence>0 AND e.sequence>0 AND older.sequence<e.sequence)
                            OR (older.sequence=0 AND older.created_at<e.created_at)
                        )
                  )
                ORDER BY e.created_at ASC
                LIMIT ?
                """,
                (time.time(), self.batch_size),
            ).fetchall()
        if not rows:
            return False
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["environment"]), []).append(row)
        for environment, group in grouped.items():
            self._deliver_group(environment, group)
        return True

    def _deliver_group(self, environment: str, rows: list[sqlite3.Row]) -> None:
        url = self.delivery_urls.get(environment, "")
        secret = self.secrets.get(environment, "")
        if not url or len(secret) < 32:
            self._delivery_failed(rows, "Destino ou chave do ambiente não configurado.")
            return
        events = []
        valid_rows = []
        for row in rows:
            try:
                vehicle = json.loads(self.fernet.decrypt(bytes(row["payload_encrypted"])).decode("utf-8"))
            except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
                self._mark_permanent_failure(str(row["event_id"]), "Evento local corrompido.")
                continue
            events.append({
                "event_id": str(row["event_id"]),
                "account_id": int(row["account_id"]),
                "source_at": str(row["source_at"]),
                "sequence": int(row["sequence"] or 0),
                "state_changed": bool(row["state_changed"]),
                "event_kind": str(row["event_kind"] or "change"),
                "vehicle": vehicle,
            })
            valid_rows.append(row)
        if not events:
            return
        body = canonical_json({"events": events, "gateway_version": ENGINE_VERSION, "sent_at": utc_iso()})
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or "/"

        def sign_headers() -> dict[str, str]:
            """Assina o mesmo corpo com timestamp e nonce novos.

            1.12.52 — o site trata o nonce como uso único (`gateway_telemetry_nonces`).
            Repetir a entrega com o cabeçalho anterior seria recusado como
            repetição, então cada tentativa recebe sua própria assinatura.
            """
            timestamp = str(int(time.time()))
            nonce = os.urandom(16).hex()
            canonical = f"POST\n{path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
            signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
            return {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"LeapHubGateway/{ENGINE_VERSION}",
                "X-LeapHub-Timestamp": timestamp,
                "X-LeapHub-Nonce": nonce,
                "X-LeapHub-Environment": environment,
                "X-LeapHub-Signature": signature,
            }

        headers = sign_headers()
        try:
            # 1.12.50 — o PHP da hospedagem compartilhada costuma ser encerrado
            # por max_execution_time antes do timeout. Desistir primeiro devolve
            # o lote à fila com backoff curto em vez de segurar a thread de
            # entrega num socket que já não tem ninguém do outro lado.
            payload = self._post_delivery(url, headers, body, sign=sign_headers)
            if not isinstance(payload, dict):
                raise RuntimeError("Resposta de entrega inválida.")
            by_id = {str(item.get("event_id")): item for item in (payload.get("results") or []) if isinstance(item, dict)}
            delivered_ids = []
            failed_rows = []
            # 1.12.74 — recusa permanente sai da fila em vez de voltar para ela.
            #
            # Medido em 09/08/2026, com o site na 1.12.327: o MESMO evento foi
            # recusado a cada ~2 min das 06:04 às 12:48, ~700 por dia. O site
            # dizia "recusado", este laço entendia "adiado" e o backoff tem teto
            # de 120 s — a repetição nunca desacelerava. A causa era um veículo
            # não confirmado naquela conta, e nenhuma repetição confirma veículo.
            #
            # O site agora marca `permanent` por evento. Só isso tira da fila:
            # ausência da marca continua sendo "tente de novo", que é o
            # comportamento de sempre e o que um site antigo produz.
            discarded: list[tuple[sqlite3.Row, str]] = []
            for row in valid_rows:
                item = by_id.get(str(row["event_id"]))
                if item and item.get("ok") is True:
                    delivered_ids.append(str(row["event_id"]))
                elif item and item.get("permanent") is True:
                    discarded.append((row, str(item.get("message") or "O site recusou o evento em definitivo.")))
                else:
                    failed_rows.append(row)
            if delivered_ids:
                now = utc_iso()
                with self.lock, self._db() as db:
                    db.executemany("UPDATE events SET status='delivered', delivered_at=?, last_error=NULL WHERE event_id=?", [(now, event_id) for event_id in delivered_ids])
                    subscription_ids = sorted({str(row["subscription_id"]) for row in valid_rows if str(row["event_id"]) in delivered_ids})
                    db.executemany("UPDATE subscriptions SET last_delivery_at=?, updated_at=? WHERE subscription_id=?", [(now, now, sid) for sid in subscription_ids])
            for row, reason in discarded:
                self._mark_permanent_failure(str(row["event_id"]), reason)
            if discarded:
                # O motivo vai no log porque descarte de leitura precisa ficar
                # explicado: quem lê "1 evento descartado" tem de saber por quê
                # sem abrir o banco.
                LOG.warning(
                    "Entrega de %s evento(s) descartada em definitivo pelo site: %s",
                    len(discarded),
                    discarded[0][1],
                )
            if failed_rows:
                self._delivery_failed(failed_rows, "O site recusou parte do lote.")
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            http.client.HTTPException,
            OSError,
            TimeoutError,
            ValueError,
            RuntimeError,
            json.JSONDecodeError,
        ) as exc:
            self._close_delivery_connection()
            self._delivery_failed(valid_rows, connector.clean_message(str(exc)))

    def _announce_telemetry_confirmation_async(
        self,
        environment: str,
        item: dict[str, Any],
    ) -> bool:
        """Envie ao site o veredito final ja provado pela telemetria FAST.

        E apenas notificacao/bookkeeping: thread daemon, sem retry, sem comando
        fisico, sem account/session/connector lock e sem alterar a cadencia.
        """
        request_id = str(item.get("request_id") or "").strip()[:96]
        command_key = str(item.get("command_key") or "").strip().lower()[:80]
        if not request_id or not bool(item.get("confirmed")):
            return False
        try:
            reads = max(0, int(item.get("poll_count") or 0))
        except (TypeError, ValueError):
            reads = 0
        try:
            elapsed = max(0, int(float(item.get("elapsed") or 0)))
        except (TypeError, ValueError):
            elapsed = 0
        result = {
            "ok": True,
            "accepted": True,
            "request_id": request_id,
            "command": command_key,
            "message": "A acao foi confirmada por uma leitura nova do veiculo.",
            "command_dispatched": True,
            "cloud_accepted": True,
            "confirmation_pending": False,
            "confirmation_reason": None,
            "verified_by_gateway": True,
            "vehicle_confirmed": True,
            "not_applied": False,
            "applied": True,
            "final_outcome": "confirmed",
            "confirmation_source": "telemetry_match",
            "confirmation_reads": reads,
            "confirmation_elapsed_seconds": elapsed,
            "connector_version": connector.CONNECTOR_VERSION,
            "gateway_version": ENGINE_VERSION,
        }
        def deliver() -> None:
            try:
                delivered = self.announce_command_result(environment, request_id, result)
                if delivered:
                    LOG.info(
                        "Veredito final de %s (%s) anunciado ao site apos confirmacao FAST.",
                        command_key or "desconhecido",
                        request_id,
                    )
            except Exception as exc:  # noqa: BLE001
                LOG.debug(
                    "Anuncio final de %s (%s) nao chegou ao site: %s",
                    command_key or "desconhecido",
                    request_id,
                    connector.clean_message(str(exc)),
                )
        try:
            thread = threading.Thread(
                target=deliver,
                name=f"leaphub-confirm-announce-{request_id[:12]}",
                daemon=True,
            )
            thread.start()
            return True
        except RuntimeError as exc:
            LOG.debug(
                "Anuncio final de %s (%s) nao pode iniciar thread: %s",
                command_key or "desconhecido",
                request_id,
                connector.clean_message(str(exc)),
            )
            return False

    def announce_command_result(self, environment: str, request_id: str, result: dict[str, Any]) -> bool:
        """Avisa o site, no mesmo instante, que o worker terminou um comando.

        1.12.78 — antes, o site só descobria o desfecho na próxima volta do
        cron. Medido em 12/08/2026 (`unlock`, conta acct_1c8b987d): o carro
        obedeceu em ~3 s, o worker terminou em 6,2 s e a tela só confirmou entre
        41 s e 65 s depois. O navegador já perguntava a cada 4-6 s e recebia
        `executing` em todas as vezes — não havia nada novo para ler, porque o
        desfecho existia apenas aqui dentro.

        Melhor esforço, e deliberadamente FORA da conexão da thread de entrega:
        usar `_post_delivery` colocaria o anúncio atrás de um lote de telemetria
        no mesmo `_delivery_guard`, que é exatamente a fila que ele veio
        desfazer. Qualquer falha é silenciosa — o ciclo do cron continua sendo a
        rede de segurança, e um site anterior à 1.12.333 simplesmente responde
        404.
        """
        request_id = str(request_id or "").strip()
        if not request_id or not isinstance(result, dict) or not result:
            return False
        url = self.delivery_urls.get(environment, "")
        secret = self.secrets.get(environment, "")
        if not url or len(secret) < 32:
            return False
        if not url.endswith(COMMAND_ANNOUNCE_SOURCE_SUFFIX):
            # Destino fora do formato conhecido: sem palpite sobre a rota.
            return False
        url = url[: -len(COMMAND_ANNOUNCE_SOURCE_SUFFIX)] + COMMAND_ANNOUNCE_TARGET_SUFFIX

        try:
            body = json.dumps(
                {
                    "request_id": request_id,
                    "result": result,
                    "gateway_version": ENGINE_VERSION,
                    "sent_at": utc_iso(),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                default=connector.json_default,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            LOG.debug("Anúncio de comando não pôde ser serializado: %s", exc)
            return False

        parsed = urllib.parse.urlparse(url)
        path = parsed.path or "/"
        timestamp = str(int(time.time()))
        nonce = os.urandom(16).hex()
        canonical = f"POST\n{path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"LeapHubGateway/{ENGINE_VERSION}",
            "Content-Length": str(len(body)),
            "Connection": "close",
            "X-LeapHub-Timestamp": timestamp,
            "X-LeapHub-Nonce": nonce,
            "X-LeapHub-Environment": environment,
            "X-LeapHub-Signature": hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest(),
        }
        target = f"{path}?{parsed.query}" if parsed.query else path

        connection: http.client.HTTPConnection | None = None
        try:
            if parsed.scheme == "https":
                connection = http.client.HTTPSConnection(
                    parsed.hostname or "", parsed.port, timeout=COMMAND_ANNOUNCE_TIMEOUT_SECONDS
                )
            elif parsed.scheme == "http":
                connection = http.client.HTTPConnection(
                    parsed.hostname or "", parsed.port, timeout=COMMAND_ANNOUNCE_TIMEOUT_SECONDS
                )
            else:
                return False
            connection.request("POST", target, body=body, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            response.read(65536)
        except Exception as exc:
            # Amplo de propósito: este anúncio é um atalho, e nenhuma falha dele
            # pode derrubar o worker que já concluiu o comando com sucesso.
            LOG.debug(
                "Anúncio do comando %s não chegou ao site: %s",
                request_id[:12],
                connector.clean_message(str(exc)),
            )
            return False
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

        if 200 <= status < 300:
            return True
        LOG.debug("O site respondeu HTTP %s ao anúncio do comando %s.", status, request_id[:12])
        return False

    def _post_delivery(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        sign: Callable[[], dict[str, str]] | None = None,
    ) -> Any:
        """POST assinado ao site reaproveitando a conexão TLS entre lotes.

        1.12.51 — cada lote abria uma conexão nova. Com o lote menor recomendado
        para hospedagem compartilhada isso multiplicou os handshakes TLS saindo
        de uma conexão residencial, e o handshake passou a custar mais que a
        própria entrega. A conexão é usada apenas pela thread de entrega e é
        descartada em qualquer erro de transporte, então nenhuma resposta pode
        ser lida fora de ordem.

        1.12.52 — faltava a outra metade do keep-alive. `http.client` não
        verifica se o socket do pool continua aberto: ele escreve e só descobre
        no `getresponse()`. Como a hospegadem fecha a conexão ociosa em poucos
        segundos e os lotes saem a cada 20-120s, praticamente toda entrega
        reaproveitada falhava com "Remote end closed connection without
        response" — sem o PHP sequer rodar — e o lote voltava para o backoff.
        Agora a conexão ociosa além da janela é descartada antes do envio, e uma
        falha de transporte sobre conexão reaproveitada ganha uma tentativa
        imediata em conexão nova, com assinatura nova.
        """
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if not host:
            raise RuntimeError("Destino de entrega sem host válido.")
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        key = f"{parsed.scheme}://{host}:{parsed.port or ''}"
        # Sem `sign` não há como renovar o nonce, e o site recusaria a repetição
        # como requisição repetida. Nesse caso vale a tentativa única de antes.
        attempts = 2 if sign is not None else 1

        with self._delivery_guard:
            for attempt in range(attempts):
                reused = self._prepare_delivery_connection(key, parsed)
                connection = self._delivery_connection
                if connection is None:
                    raise RuntimeError("Conexão de entrega indisponível.")
                request_headers = dict(headers if attempt == 0 else sign())
                request_headers["Content-Length"] = str(len(body))
                request_headers.setdefault("Connection", "keep-alive")
                try:
                    connection.request("POST", target, body=body, headers=request_headers)
                    response = connection.getresponse()
                    raw = response.read(2 * 1024 * 1024)
                    status = int(response.status)
                    if response.will_close:
                        self._close_delivery_connection()
                    else:
                        self._delivery_connection_idle_since = time.monotonic()
                        self._remember_delivery_idle_window(response.getheader("Keep-Alive", ""))
                    break
                except Exception:
                    # Um socket meio-fechado nunca volta ao pool: a próxima
                    # entrega leria a resposta do lote anterior.
                    self._close_delivery_connection()
                    # Só a primeira tentativa sobre conexão reaproveitada pode
                    # repetir. Ali o servidor comprovadamente não respondeu, a
                    # ingestão é idempotente pelo event_id e a alternativa era
                    # esperar o backoff inteiro por um socket morto.
                    if reused and attempt + 1 < attempts:
                        LOG.debug("Conexão de entrega reaproveitada estava fechada; repetindo em conexão nova.")
                        continue
                    raise

        if status < 200 or status >= 300:
            raise RuntimeError(f"O site respondeu HTTP {status} à entrega de telemetria.")
        return json.loads(raw.decode("utf-8"))

    def _prepare_delivery_connection(self, key: str, parsed: urllib.parse.ParseResult) -> bool:
        """Devolve True quando a conexão do pool pôde ser reaproveitada."""
        connection = self._delivery_connection
        if connection is not None and self._delivery_connection_key != key:
            self._close_delivery_connection()
            connection = None
        if connection is not None and time.monotonic() - self._delivery_connection_idle_since >= self._delivery_idle_max:
            # Passou da janela de keep-alive anunciada/presumida do servidor. O
            # socket provavelmente já foi fechado do outro lado e escrever nele
            # custaria o lote inteiro.
            self._close_delivery_connection()
            connection = None
        if connection is not None:
            return True
        if parsed.scheme == "https":
            connection = http.client.HTTPSConnection(parsed.hostname or "", parsed.port, timeout=25)
        elif parsed.scheme == "http":
            connection = http.client.HTTPConnection(parsed.hostname or "", parsed.port, timeout=25)
        else:
            raise RuntimeError("Esquema de entrega não suportado.")
        self._delivery_connection = connection
        self._delivery_connection_key = key
        self._delivery_connection_idle_since = time.monotonic()
        return False

    def _remember_delivery_idle_window(self, keep_alive_header: str) -> None:
        """Usa o `Keep-Alive: timeout=N` do servidor quando ele informa um.

        Sem o cabeçalho vale o padrão conservador. A margem de um segundo cobre
        a latência da própria requisição seguinte.
        """
        for part in str(keep_alive_header or "").split(","):
            name, _, value = part.strip().partition("=")
            if name.strip().lower() != "timeout":
                continue
            try:
                advertised = float(value.strip())
            except ValueError:
                return
            self._delivery_idle_max = max(
                DELIVERY_IDLE_MIN_SECONDS,
                min(DELIVERY_IDLE_MAX_SECONDS, advertised - 1.0),
            )
            return

    def _close_delivery_connection(self) -> None:
        with self._delivery_guard:
            connection, self._delivery_connection = self._delivery_connection, None
            self._delivery_connection_key = ""
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass

    def _delivery_failed(self, rows: list[sqlite3.Row], message: str) -> None:
        now = time.time()
        updates = []
        for row in rows:
            attempts = int(row["attempts"] or 0) + 1
            # 1.12.50 — o teto anterior de 1800s deixava a telemetria de um
            # usuário muda por meia hora depois de duas lentidões da hospedagem.
            # A fila é persistente e o event_id é idempotente; repetir em até 2min
            # não duplica nada e não custa chamada à nuvem Leapmotor.
            delay = min(120, max(10, 5 * (2 ** min(attempts, 5)))) + random.uniform(0, 5)
            updates.append((attempts, now + delay, str(message)[:500], str(row["event_id"])))
        with self.lock, self._db() as db:
            db.executemany("UPDATE events SET attempts=?, next_attempt_at=?, last_error=? WHERE event_id=?", updates)
        LOG.warning("Entrega de %s evento(s) adiada: %s", len(rows), message)

    def _mark_permanent_failure(self, event_id: str, message: str) -> None:
        with self.lock, self._db() as db:
            db.execute("UPDATE events SET status='failed', last_error=? WHERE event_id=?", (message[:500], event_id))

    def _reschedule(self, subscription_id: str, delay: int, status: str, error: str | None, failed: bool) -> None:
        now = utc_iso()
        with self.schedule_lock, self._db(timeout_seconds=2.0) as db:
            if failed:
                db.execute(
                    "UPDATE subscriptions SET status=?, next_run_at=?, last_run_at=?, last_error=?, consecutive_failures=consecutive_failures+1, updated_at=? WHERE subscription_id=?",
                    (status, time.time() + delay + random.uniform(0, 5), now, str(error or "")[:500], now, subscription_id),
                )
            else:
                db.execute(
                    "UPDATE subscriptions SET status=?, next_run_at=?, last_run_at=?, last_error=?, updated_at=? WHERE subscription_id=?",
                    (status, time.time() + delay, now, str(error or "")[:500] or None, now, subscription_id),
                )

    def _expire_idle_sessions(self, now_epoch: float) -> None:
        """Descarta sessões por inatividade real, não pelo fim da janela de coleta.

        Roda a cada ciclo: é uma varredura em memória, sem disco, e é ela que
        devolve o cliente Leapmotor depois da inatividade. Nunca deve ficar
        atrás do throttle da retenção da fila.
        """
        with self.session_lock:
            stale_sessions = [
                sid for sid, session in self.sessions.items()
                if now_epoch - float(session.get("last_used_at") or 0) >= self.session_idle_seconds
            ]
        for subscription_id in stale_sessions:
            self._close_session(subscription_id)


    def _maintenance(self) -> str:
        """Limpeza local limitada, interrompivel e subordinada a comandos."""
        now_epoch = time.time()
        # Sessao ociosa e memoria; nao precisa esperar a janela da poda em disco.
        self._expire_idle_sessions(now_epoch)
        if now_epoch - self._maintenance_last_at < MAINTENANCE_INTERVAL_SECONDS:
            return "throttled"

        cutoff = now_epoch - self.retention_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat().replace("+00:00", "Z")
        batch = int(MAINTENANCE_BATCH_SIZE)

        # Toda descoberta e SELECT pode levar o tempo que o volume precisar sem
        # possuir writer lock. WAL mantem os comandos/escritas livres. So as
        # mutacoes finais recebem listas pequenas de PKs.
        with self._db(timeout_seconds=MAINTENANCE_BUSY_TIMEOUT_SECONDS) as db:
            command_active = db.execute(
                "SELECT 1 FROM subscriptions WHERE enabled=1 AND command_until>? LIMIT 1",
                (now_epoch,),
            ).fetchone()
            confirmation_active = db.execute(
                "SELECT 1 FROM command_confirmations WHERE status='pending' AND expires_at>? LIMIT 1",
                (now_epoch,),
            ).fetchone()
            if command_active is not None or confirmation_active is not None:
                return "command_priority"

            expired_windows = [str(row[0]) for row in db.execute(
                "SELECT subscription_id FROM subscriptions WHERE enabled=1 AND active_until<=? "
                "AND status NOT IN ('idle','background','disabled','auth_required','cooldown') LIMIT ?",
                (now_epoch, batch),
            ).fetchall()]
            if expired_windows:
                placeholders = ",".join("?" for _ in expired_windows)
                expired_status = "background" if self.background_enabled else "idle"
                db.execute(
                    f"UPDATE subscriptions SET status=?,interactive_until=0,command_until=0,last_error=NULL,updated_at=? "
                    f"WHERE subscription_id IN ({placeholders})",
                    (expired_status, utc_iso(), *expired_windows),
                )

            stale_pending = [str(row[0]) for row in db.execute(
                "SELECT event_id FROM events WHERE status='pending' AND created_at<? ORDER BY created_at ASC LIMIT ?",
                (cutoff_iso, batch),
            ).fetchall()]
            if stale_pending:
                placeholders = ",".join("?" for _ in stale_pending)
                db.execute(
                    f"UPDATE events SET status='failed',last_error=? WHERE event_id IN ({placeholders})",
                    ("A fila desistiu: nao entregue dentro da janela de retencao.", *stale_pending),
                )
                LOG.warning(
                    "Fila de telemetria desistiu de %s evento(s) nao entregue(s) ha mais de %s dia(s).",
                    len(stale_pending),
                    self.retention_days,
                )

            old_delivered = [str(row[0]) for row in db.execute(
                "SELECT event_id FROM events WHERE status='delivered' "
                "AND COALESCE(delivered_at,created_at)<? ORDER BY created_at ASC LIMIT ?",
                (cutoff_iso, batch),
            ).fetchall()]
            if old_delivered:
                placeholders = ",".join("?" for _ in old_delivered)
                db.execute(f"DELETE FROM events WHERE event_id IN ({placeholders})", old_delivered)

            old_failed = [str(row[0]) for row in db.execute(
                "SELECT event_id FROM events WHERE status='failed' AND created_at<? ORDER BY created_at ASC LIMIT ?",
                (cutoff_iso, batch),
            ).fetchall()]
            if old_failed:
                placeholders = ",".join("?" for _ in old_failed)
                db.execute(f"DELETE FROM events WHERE event_id IN ({placeholders})", old_failed)

            total = int(db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
            if total > self.queue_max:
                trim_limit = min(batch, total - self.queue_max)
                terminal = [str(row[0]) for row in db.execute(
                    "SELECT event_id FROM events WHERE status IN ('delivered','failed') "
                    "ORDER BY created_at ASC LIMIT ?",
                    (trim_limit,),
                ).fetchall()]
                if terminal:
                    placeholders = ",".join("?" for _ in terminal)
                    db.execute(f"DELETE FROM events WHERE event_id IN ({placeholders})", terminal)

        # So uma passada realmente concluida abre o throttle historico de 60 segundos.
        self._maintenance_last_at = time.time()
        return "cleaned"
