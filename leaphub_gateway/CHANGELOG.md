# Changelog

## 1.11.54.3

- Distribuição oficial pelo GitHub Container Registry.
- Instalação e atualização sem compilação local no Home Assistant.
- Suporte a `amd64` e `aarch64`.
- Download do Cloudflared adaptado por arquitetura e validado por SHA-256.
- Repositório oficial com documentação, botão de instalação e workflows automáticos.
- URL e metadados atualizados para o repositório oficial.

## 1.11.54.2

- Dockerfile reorganizado para preservar o cache das camadas pesadas em compilações locais.
- Limites de conexão e tempo no download do Cloudflared.
- Correção da biblioteca compartilhada do Python.

## 1.11.54.1

- Migração para a imagem oficial `base-python` do Home Assistant.
- Correção do erro `libpython3.12.so.1.0`.

## 1.11.54

- App único para Connector, OCPP Beta, OCPP Produção e Cloudflare Tunnel.
- Painel Ingress responsivo com saúde, PID, reinícios, testes e logs recentes.
- Supervisão individual dos processos.
- Token do Tunnel fora da linha de comando.
- Migração reversível.
- Ícone, logotipo, traduções, documentação e política AppArmor.
