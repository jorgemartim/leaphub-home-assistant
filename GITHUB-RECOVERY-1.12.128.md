# Recuperação GitHub — Gateway 1.12.128

Release candidata da orientação física dos pneus do Leapmotor C10. Se a
publicação for interrompida, mantenha instalada a 1.12.127: ela preserva fila,
telemetria, comandos, banco SQLite e OCPP; apenas entrega as pressões do C10 na
orientação antiga da biblioteca.

Antes de anunciar a versão no Home Assistant, a suíte completa, o build da
imagem pré-compilada, o manifesto e o acesso anônimo ao digest do GHCR precisam
estar aprovados. Nenhum rollback deve remover `/data`, recriar a fila ou apagar
telemetria coletada.
