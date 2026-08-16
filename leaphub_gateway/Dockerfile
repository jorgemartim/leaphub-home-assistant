FROM python:3.12-slim-bookworm

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=dev
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LEAPHUB_RUNTIME_DIR=/data/runtime \
    PYTHONPATH=/app \
    PATH=/usr/local/bin:/usr/bin:/bin

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    if [ "${BUILD_ARCH}" != "amd64" ]; then \
      echo "Arquitetura ainda não suportada nesta versão: ${BUILD_ARCH}" >&2; \
      exit 1; \
    fi

# O cloudflared é obtido com checksum somente quando o túnel embutido é ativado.
# Assim atualizações normais não baixam um binário grande durante o build local.

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --requirement /app/requirements.txt

# Os módulos críticos ficam em /app e também em site-packages com nomes exclusivos.
# Isso evita falhas de importação mesmo que o diretório de trabalho mude em runtime.
COPY connector.py telemetry_engine.py privacy.py /app/
COPY connection_orchestrator.py event_transport.py official_trip_probe.py /app/
RUN python3 - <<'PY'
from pathlib import Path
import shutil
import site
base = Path('/app')
target_dir = Path(site.getsitepackages()[0])
modules = {
    'connector.py': 'leaphub_connector.py',
    'telemetry_engine.py': 'leaphub_telemetry_engine.py',
    'privacy.py': 'leaphub_privacy.py',
    'connection_orchestrator.py': 'leaphub_connection_orchestrator.py',
    'event_transport.py': 'leaphub_event_transport.py',
    'official_trip_probe.py': 'leaphub_official_trip_probe.py',
}
for source_name, target_name in modules.items():
    source = base / source_name
    if not source.is_file() or source.stat().st_size < 1000:
        raise SystemExit(f'{source_name} ausente ou incompleto')
    target = target_dir / target_name
    shutil.copy2(source, target)
    print(f'Módulo instalado em {target}')
PY

COPY connector_server.py ocpp_gateway.py gateway_manager.py /app/

# A imagem só é publicada quando os módulos críticos importam no mesmo modo do runtime.
RUN python3 - <<'PY'
from pathlib import Path
import importlib.util
import leaphub_connector
import leaphub_telemetry_engine
import leaphub_privacy
import leaphub_connection_orchestrator
import leaphub_event_transport
import leaphub_official_trip_probe
from leaphub_telemetry_engine import TelemetryEngine
assert Path('/app/connector.py').is_file()
assert Path('/app/telemetry_engine.py').is_file()
assert leaphub_connector.CONNECTOR_VERSION
assert leaphub_telemetry_engine.ENGINE_VERSION
assert leaphub_privacy.PRIVACY_VERSION
assert leaphub_connection_orchestrator.ORCHESTRATOR is not None
assert leaphub_event_transport.EVENT_TRANSPORT is not None
assert leaphub_official_trip_probe.PROBE_VERSION == "1.12.100"
assert TelemetryEngine is not None
import os
import sqlite3
import tempfile
import threading
with tempfile.TemporaryDirectory() as temp_dir:
    os.environ['LEAPHUB_TELEMETRY_DIR'] = temp_dir
    engine = TelemetryEngine({}, {'staging': 'x' * 32, 'production': ''}, threading.BoundedSemaphore(1))
    # sqlite3.connect como context manager encerra a transacao, nao a conexao:
    # sem o close explicito o arquivo da fila fica aberto ate o processo sair.
    probe = sqlite3.connect(engine.db_path)
    try:
        journal = str(probe.execute('PRAGMA journal_mode').fetchone()[0]).lower()
    finally:
        probe.close()
    # 1.12.51 — o journal deixou de ser fixo. O contrato agora e: WAL quando o
    # volume aceita, DELETE quando nao aceita, e o motor precisa reportar o modo
    # que realmente ficou valendo. Prender a imagem a um unico modo foi o que
    # reprovou o build da 1.12.50 assim que o volume da imagem aceitou WAL.
    assert journal in ('wal', 'delete'), journal
    assert engine.storage_journal_mode == journal, (engine.storage_journal_mode, journal)
    assert engine.storage_status()['journal_mode'] == journal
    assert engine.storage_status()['healthy'] is True
    with engine.lock, engine._db() as db:
        assert int(db.execute('SELECT COUNT(*) FROM subscriptions').fetchone()[0]) == 0
    engine.close_storage()
for module in ('connector_server', 'ocpp_gateway', 'gateway_manager'):
    spec = importlib.util.find_spec(module)
    if spec is None:
        raise SystemExit(f'Módulo ausente: {module}')
print('Autoteste de importação de Connector e telemetria concluído com sucesso.')
PY

RUN python3 -m compileall -q /app \
    && mkdir -p /data/runtime /data/logs /data/telemetry /data/security \
    && chmod 0700 /data/runtime /data/logs /data/telemetry /data/security

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.name="Leap Hub Gateway" \
  io.hass.description="Gateway unificado Leapmotor, OCPP e Cloudflare para o Leap Hub" \
  io.hass.url="https://github.com/jorgemartim/leaphub-home-assistant" \
  org.opencontainers.image.title="Leap Hub Gateway" \
  org.opencontainers.image.description="Gateway unificado Leapmotor, OCPP e Cloudflare para Home Assistant" \
  org.opencontainers.image.source="https://github.com/jorgemartim/leaphub-home-assistant" \
  org.opencontainers.image.version="${BUILD_VERSION}" \
  org.opencontainers.image.licenses="LicenseRef-Proprietary"

EXPOSE 8092 8093 8094 8099
CMD ["python3", "-u", "/app/gateway_manager.py"]
