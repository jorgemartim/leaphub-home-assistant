# Leap Hub Gateway 1.12.17

- Corrige o OCPP único para carregar somente o ambiente realmente ativado; o ambiente desativado não é mais consultado.
- Bloqueia configuração com Beta e Produção OCPP ativos simultaneamente, evitando eventos e comandos concorrentes.
- A execução direta também exige um ambiente explícito e nunca consulta os dois destinos para descobrir a rota.
- Usa o limite de conexões do ambiente ativo e reduz o padrão para 20.
- Reseta o backoff de reinício após cinco minutos estáveis e rotaciona logs locais para evitar lentidão e disco cheio.
- Confia em cabeçalhos de IP encaminhado somente quando a conexão veio de proxy local/privado.
- Distribui as consultas de comandos OCPP com jitter e reduz o envio de status do Gateway para cada 30 segundos.
- Preserva API v2, telemetria, 25 comandos, filas SQLite, porta pública 8092 e build local do Home Assistant.
