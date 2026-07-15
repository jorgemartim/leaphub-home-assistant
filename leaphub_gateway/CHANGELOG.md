# Changelog

## 1.11.57

- Envia `outColor` para o Leap Hub e preserva aliases de cor encontrados no retorno bruto.
- Amplia o estado visual com portas, vidros e percentuais individuais, teto solar, cortina, luzes, espelhos, sentinela e segurança.
- Envia climatização avançada, bancos, volante aquecido, conectividade, plano de carga, tipo de conector, tempo restante e estado dos pneus.
- Mantém compatibilidade com leituras antigas e com campos ausentes por modelo ou permissão.
- Atualiza a versão do mapeamento para 1.11.57.

## 1.11.56.1

- Corrige a inclusão e a importação do motor de telemetria na imagem publicada.
- Instala o módulo também em site-packages com nome interno exclusivo.
- Adiciona teste de runtime da imagem exata antes da publicação no GHCR.
- Mantém configurações, fila persistente, OCPP e Tunnel sem alteração.

## 1.11.56.1

- Corrige `ModuleNotFoundError: No module named leaphub_connector/connector`.
- Instala o Connector em `site-packages` com nome interno exclusivo.
- Adiciona autoteste obrigatório de importação na compilação Docker.
- Adiciona validação de presença e tamanho do arquivo `connector.py`.
- Registra no log o caminho do módulo carregado antes de iniciar os serviços.

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
