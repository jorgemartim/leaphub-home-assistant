# Recuperação GitHub — Gateway 1.12.125

Release candidata que corrige o timeout efetivo do login automático: o teto de
4 segundos da telemetria deixa de ser elevado silenciosamente para 12 segundos.
Os comandos mantêm timeout próprio, despacho único e confirmação autoritativa.

Não há retry físico novo, migration, alteração de schema, limpeza, exclusão ou
transformação de dados.

Validação obrigatória antes da publicação: suíte completa do Gateway, build da
imagem, validação do manifesto e acesso anônimo ao digest publicado no GHCR.
