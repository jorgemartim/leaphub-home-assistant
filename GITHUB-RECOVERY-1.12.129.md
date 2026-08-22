# Recuperação GitHub — Gateway 1.12.129

Release candidata do polling OCPP em lote. A instalação preserva `/data`, fila
persistente, rotas, comandos pendentes e telemetria. Instale o Site 1.12.417
antes do Gateway para ativar imediatamente o contrato agregado.

Se a publicação for interrompida, a 1.12.128 continua compatível com o Site
novo pelo endpoint individual. Nenhum rollback deve apagar `/data` ou recriar a
fila SQLite.
