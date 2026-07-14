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

# O módulo é copiado para /app e também instalado com um nome interno exclusivo.
COPY connector.py /app/connector.py
RUN python3 - <<'PY'
from pathlib import Path
import shutil
import site
source = Path('/app/connector.py')
if not source.is_file() or source.stat().st_size < 1000:
    raise SystemExit('connector.py ausente ou incompleto')
target = Path(site.getsitepackages()[0]) / 'leaphub_connector.py'
shutil.copy2(source, target)
print(f'Connector instalado em {target}')
PY

COPY connector_server.py telemetry_engine.py ocpp_gateway.py gateway_manager.py /app/

# A imagem só é publicada quando todos os módulos realmente podem ser importados.
RUN python3 - <<'PY'
from pathlib import Path
import importlib.util
import leaphub_connector
assert Path('/app/connector.py').is_file()
assert leaphub_connector.CONNECTOR_VERSION
assert leaphub_connector.package_version() is not None
for module in ('connector_server', 'telemetry_engine', 'ocpp_gateway', 'gateway_manager'):
    spec = importlib.util.find_spec(module)
    if spec is None:
        raise SystemExit(f'Módulo ausente: {module}')
print('Autoteste de importação concluído com sucesso.')
PY

RUN python3 -m compileall -q /app \
    && mkdir -p /data/runtime /data/logs

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
