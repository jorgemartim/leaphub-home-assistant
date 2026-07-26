## 1.12.35

- Confirmação de comandos pode iniciar imediatamente após o envio sem ser bloqueada pela reserva pós-comando; novas ações manuais continuam preemptando a telemetria em pontos seguros.
- Event Transport direciona wake-up ao veículo quando o evento possui identificador, reduzindo assinaturas acordadas sem necessidade.
- Comandos concluídos geram um hint interno seguro para acelerar a primeira leitura de confirmação, mantendo REST como transporte real e MQTT desativado.
- Connection Orchestrator passa a medir latência da telemetria FAST/SLOW e quantas coletas cederam prioridade para comandos.
- Distribuição pré-compilada via GHCR preservada; pipeline GHCR da 1.12.34 foi preservado sem mudanças funcionais.
