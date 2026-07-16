# Leap Hub Gateway 1.11.74

- Nonce e assinatura canônica nas chamadas internas OCPP.
- Timeout de leitura por conexão HTTP para reduzir slowloris.
- Cache de travas por conta limitado e limpo com segurança.
- Mantém isolamento de sessão, cooldown e telemetria interativa da 1.11.73.
- Proteção HMAC contra replay persistida em SQLite, inclusive após reinício do App.
- Corrigida inicialização duplicada do motor de telemetria.
- Falha de autenticação agora retorna `auth_required=true`.
