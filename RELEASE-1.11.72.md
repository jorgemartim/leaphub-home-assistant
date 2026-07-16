# Gateway 1.11.72

- Adiciona perfil interativo de telemetria, ativo apenas enquanto uma aba visível do Leap Hub renova a presença.
- Consulta o estado em aproximadamente 20 segundos no modo interativo e volta automaticamente ao perfil econômico quando o usuário sai.
- Reutiliza a sessão existente da conta e mantém as travas, cooldowns e bloqueios de autenticação.
- Envia heartbeat confirmado em até 40 segundos mesmo quando o estado não mudou, mantendo “Última leitura” preciso.
- Separa os estados de porta e vidro no compositor oficial, corrigindo o vidro traseiro desenhado sobre a porta do motorista.
- Mantém uma única coleta por conta, incluindo contas com vários veículos.
