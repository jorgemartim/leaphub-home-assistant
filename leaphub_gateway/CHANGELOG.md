## 1.12.114

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- adiciona sinais paralelos de viagem: velocidade bruta `1319`, hodometro bruto `1318` e timestamp do veiculo, sem substituir os campos legados;
- persiste por veiculo os hemisferios GPS confirmados e protege contra quadros isolados que perdem o sinal negativo;
- ativa burst de viagem em 8s somente quando ha evidencia de conducao;
- snapshots repetidos recuam progressivamente ate o teto anterior, evitando chamadas rapidas inuteis quando a nuvem congela;
- preserva exatamente confirmacao 5/5/8, tela interativa, auth/cooldown, OCPP, maintenance 1.12.112 e fila SQLite;
- preserva fence mecanico 1.12.113, escala C10 0-10, defrost 2/0, Prepare, SAFE retry e todos os payloads fisicos;
- mantem `config.yaml` em 1.12.113 ate a publicacao normal via CI/GHCR.
