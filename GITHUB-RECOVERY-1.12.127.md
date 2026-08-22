# Recuperação GitHub — Gateway 1.12.127

Release candidata da confirmação rápida dos bancos e limpeza do log de
diagnóstico. Se a publicação for interrompida, mantenha instalada a 1.12.126:
ela preserva comandos, telemetria, fila SQLite e o pulso redundante do
scheduler; apenas confirma os bancos pela cadência anterior e mantém os dumps
de clima no log normal.

Antes de anunciar a versão no Home Assistant, a suíte completa, o build da
imagem pré-compilada, o manifesto e o acesso anônimo ao digest do GHCR precisam
estar aprovados. Nenhum rollback deve remover `/data` ou recriar a fila.
