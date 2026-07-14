# Changelog

## 1.11.56

- Sincronização automática adaptativa: 5 s em viagem e recarga, 10 s com cabo conectado, 30 s estacionado e 120 s em repouso.
- Proteção com jitter, fila por conta, recuo exponencial e pausa automática ao detectar limitação.
- Logs de ciclos bem-sucedidos passam para DEBUG; mudanças de estado continuam visíveis.
- Painel mostra o novo perfil automático e o tempo de proteção.

# 1.11.56

- Telemetria adaptativa durante viagem, recarga, estacionamento e repouso.
- Fila SQLite persistente com credenciais e eventos criptografados.
- Entrega idempotente ao site e recuperação após indisponibilidade.
- Painel com assinaturas, fila e falhas; healthchecks sem poluir logs.
- Origens do Tunnel corrigidas para 127.0.0.1 dentro do App unificado.

# Changelog

## 1.11.56

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
