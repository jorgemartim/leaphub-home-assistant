## 1.12.42

- Mantém distribuição pré-compilada via GHCR.
- Smoke test da imagem pré-compilada não executa mais o processo de longa duração `gateway_manager.py`.
- Timeouts defensivos no teste da imagem publicada.
- Publicação em duas fases preservada: imagem primeiro, versão do Home Assistant depois.
- Sem alteração funcional de OCPP, Connector, opções ou dados persistentes em relação à 1.12.41.
