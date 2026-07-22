FROM python:3.12-slim-bookworm

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=dev
ARG CLOUDFLARED_VERSION=2026.7.1
ARG CLOUDFLARED_SHA256_AMD64=79a0ade7fc854f62c1aaef48424d9d979e8c2fcd039189d24db82b84cd146be1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LEAPHUB_RUNTIME_DIR=/data/runtime \
    PYTHONPATH=/app \
    PATH=/usr/local/bin:/usr/bin:/bin

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    if [ "${BUILD_ARCH}" != "amd64" ]; then \
      echo "Arquitetura ainda não suportada nesta versão: ${BUILD_ARCH}" >&2; \
      exit 1; \
    fi; \
    curl --fail --location --retry 3 --retry-delay 2 \
      --connect-timeout 20 --max-time 300 \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64" \
      --output /usr/local/bin/cloudflared; \
    echo "${CLOUDFLARED_SHA256_AMD64}  /usr/local/bin/cloudflared" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/cloudflared; \
    /usr/local/bin/cloudflared --version

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --requirement /app/requirements.txt

# Os módulos críticos ficam em /app e também em site-packages com nomes exclusivos.
# Isso evita falhas de importação mesmo que o diretório de trabalho mude em runtime.
COPY connector.py telemetry_engine.py privacy.py /app/
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
from leaphub_telemetry_engine import TelemetryEngine
assert Path('/app/connector.py').is_file()
assert Path('/app/telemetry_engine.py').is_file()
assert leaphub_connector.CONNECTOR_VERSION
assert leaphub_telemetry_engine.ENGINE_VERSION
assert leaphub_privacy.PRIVACY_VERSION
assert TelemetryEngine is not None
import os
import sqlite3
import tempfile
import threading
with tempfile.TemporaryDirectory() as temp_dir:
    os.environ['LEAPHUB_TELEMETRY_DIR'] = temp_dir
    engine = TelemetryEngine({}, {'staging': 'x' * 32, 'production': ''}, threading.BoundedSemaphore(1))
    with sqlite3.connect(engine.db_path) as db:
        journal = str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()
    assert journal == 'delete', journal
    assert engine.storage_status()['healthy'] is True
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
