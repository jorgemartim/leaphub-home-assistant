## 1.12.49

- Preserva a sessão Leapmotor saudável quando o site repete um `upsert` idêntico após validar as credenciais.
- Evita que uma atualização administrativa da assinatura aguarde uma telemetria em voo ou force autenticação desnecessária.
- Mantém a recuperação explícita quando não existe sessão ativa, quando as credenciais mudam ou quando a assinatura é desativada.
- Não altera comandos físicos, intervalos, filas, SQLite, OCPP, vínculos ou dados existentes.
- Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
