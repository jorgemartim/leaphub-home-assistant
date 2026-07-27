## 1.12.46

- Mantém distribuição pré-compilada via GHCR.
- Corrige a inversão de lock da telemetria: a conta é adquirida antes da vaga global do Connector.
- Uma conta ocupada não consome slot compartilhado enquanto aguarda.
- Espera de slot é interrompível por comando manual da mesma conta.
- Métricas agregadas de account wait, connector wait, yields e timeouts.
- Exportação de diagnóstico sanitizado no painel Ingress, sem logs, tokens, segredos ou identificadores.
- Nenhuma migration destrutiva; estado e filas existentes são preservados.
