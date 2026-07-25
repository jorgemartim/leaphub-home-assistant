# Leap Hub Gateway 1.12.14

Baseado integralmente na 1.12.13 corrigida e na 1.12.12 oficial, preservando API v2, todos os comandos, OCPP, Cloudflare Tunnel, filas e configurações existentes.

## Leapmotor

- preserva a sessão saudável por até seis horas de inatividade, em vez de fechar ao terminar a janela ativa;
- mantém a consulta de estado atual, mas reutiliza a lista de veículos por 30 minutos;
- reutiliza mensagens de manutenção por 30 minutos;
- aumenta o timeout de telemetria para 15 segundos, reduzindo falsos timeouts;
- identifica expiração real de token, fecha somente a sessão afetada e agenda uma única reconexão protegida;
- sincronização manual de um veículo reutiliza a lista em cache quando segura;
- mantém cooldown global, lock por conta e backoff progressivo.

## OCPP e wallbox

- verifica tráfego recebido e encerra conexões realmente mortas após 120 segundos;
- falha imediatamente comandos pendentes quando a wallbox desconecta;
- suprime transição offline quando a wallbox reconecta em até oito segundos;
- mantém ordem dos eventos durante indisponibilidade do site;
- limita a fila persistente e remove eventos antigos após sete dias;
- adiciona índices SQLite e métricas de idade da fila/liveness;
- preserva OCPP 1.6J, endpoint unificado, Beta e Produção.

## Compatibilidade

- nenhuma credencial é alterada;
- nenhum banco é apagado;
- nenhum endpoint, comando ou opção anterior é removido;
- novas opções possuem valores padrão e não exigem configuração manual.
