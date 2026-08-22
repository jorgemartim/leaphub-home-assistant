## 1.12.130

- O painel Ingress usa a versão real do add-on, eliminando o rótulo fixo `v1.12.48`.
- Novo cartão sanitizado compara apenas parâmetros numéricos não secretos com o perfil recomendado e explica valores legados que podem aumentar latência.
- Todos os campos avançados de telemetria, OCPP e Tunnel passam a ter nomes e descrições em português e inglês.
- A distribuição permanece pré-compilada no GHCR e só é anunciada ao Home Assistant depois do smoke test público.
- Nenhuma fila, credencial, telemetria, transação ou banco local é alterado.
