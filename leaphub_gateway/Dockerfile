FROM ghcr.io/home-assistant/base-python:3.12-alpine3.24

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=dev
ARG CLOUDFLARED_VERSION=2026.7.1
ARG CLOUDFLARED_SHA256_AMD64=79a0ade7fc854f62c1aaef48424d9d979e8c2fcd039189d24db82b84cd146be1
ARG CLOUDFLARED_SHA256_AARCH64=18f2c9bfc7a67a971bd96f1a5a1935def3c1e52aa386626f1566f04e9b5478d6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LEAPHUB_RUNTIME_DIR=/data/runtime \
    PATH=/usr/local/bin:/usr/bin:/bin

WORKDIR /app

RUN apk add --no-cache ca-certificates curl libstdc++

RUN set -eux; \
    case "${BUILD_ARCH}" in \
      amd64) cloudflared_arch="amd64"; cloudflared_sha="${CLOUDFLARED_SHA256_AMD64}" ;; \
      aarch64) cloudflared_arch="arm64"; cloudflared_sha="${CLOUDFLARED_SHA256_AARCH64}" ;; \
      *) echo "Arquitetura não suportada: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac; \
    curl --fail --location --retry 3 --retry-delay 2 \
      --connect-timeout 20 --max-time 300 \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-${cloudflared_arch}" \
      --output /usr/local/bin/cloudflared; \
    echo "${cloudflared_sha}  /usr/local/bin/cloudflared" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/cloudflared; \
    /usr/local/bin/cloudflared --version

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --requirement /app/requirements.txt

COPY connector.py connector_server.py ocpp_gateway.py gateway_manager.py /app/
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
