# Leap Hub Gateway 1.11.83

## Correção da fila SQLite

- Remove o uso obrigatório de `WAL` na fila persistente de telemetria.
- Migra de forma segura a fila existente para journal tradicional, preservando assinaturas e eventos já armazenados.
- Cria e valida `/data/telemetry` e os diretórios persistentes antes de iniciar o Connector.
- Corrige permissões locais dos arquivos da fila e testa gravação real no armazenamento do App.
- Mantém arquivos temporários do SQLite em memória para não depender de diretórios externos ao `/data`.
- Troca o loop de erro a cada fração de segundo por recuo progressivo de até cinco minutos.
- Informa no diagnóstico a saúde, o modo de journal e a próxima tentativa da fila persistente.

## Ajustes adicionais

- Repassa corretamente `telemetry_command_max_polls` ao processo do Connector.
- Corrige o valor padrão de telemetria estacionada para 300 segundos.
- Mantém Connector, OCPP e Cloudflare Tunnel sem alteração de chaves ou tokens.

## Atualização

1. Publique este repositório no GitHub.
2. Aguarde a imagem `1.11.83` ser criada pelo workflow.
3. Atualize o App **Leap Hub Gateway** no Home Assistant.
4. Não apague `/data/telemetry` e não remova os tokens.
5. Reinicie o App e confirme no log `Telemetria contínua iniciada` sem repetição de `unable to open database file`.
