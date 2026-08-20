# Leap Hub Gateway 1.12.118 - dependências e fechamento SQLite

Base publicada obrigatória: `fa5c5c9` (Gateway 1.12.117).

## Correções

- `cryptography==50.0.0` e `Pillow==12.3.0`, confirmados no PyPI para Python
  3.12;
- conexões OCPP, diário de comandos, nonce e leitura de status fecham
  deterministicamente ao sair de `with`, após o commit/rollback padrão do
  SQLite;
- testes OCPP deixam de depender de variável de ambiente vazada e passam a
  fechar seus bancos temporários explicitamente.

## Integridade

Não há migration nem acesso a banco operacional. Nenhum evento, comando, fila,
cursor ou dado coletado é apagado ou recalculado. Comandos físicos, Trips,
telemetria, proximidade e cadências permanecem congelados.

## Publicação em duas fases

`RELEASE_TARGET` e os módulos ficam em `1.12.118`; `config.yaml` permanece em
`1.12.117` até o CI validar a suíte, construir a imagem, executar o smoke test e
confirmar acesso anônimo à tag GHCR exata.

## Validação local

- `pip check`: sem dependências quebradas;
- versões efetivamente importadas: `cryptography 50.0.0` e `Pillow 12.3.0`;
- contratos direcionados de Fernet, imagens e SQLite: `13/13`;
- gate equivalente ao CI: `608/608` testes principais e `5/5` legados;
- repositório válido em modo staged; sem push, GHCR ou instalação.
