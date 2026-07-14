# Changelog

## 1.11.54.4

- Corrige a imagem-base que causava `apk: not found` durante a compilação local.
- Passa a usar Python 3.12 sobre Debian slim para evitar bibliotecas compartilhadas ausentes.
- Substitui o workflow quebrado por publicação direta no GitHub Container Registry.
- Publica inicialmente para `amd64`, a arquitetura do servidor atual.
- Adiciona cache de camadas para acelerar builds futuros no GitHub.

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
