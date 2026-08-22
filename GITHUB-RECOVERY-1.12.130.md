# Recuperação GitHub — Gateway 1.12.130

Release candidata de diagnóstico e configuração. A publicação continua em
duas fases: a imagem pré-compilada `1.12.130` é criada e testada no GHCR antes
de o `config.yaml` ser promovido automaticamente de 1.12.129 para 1.12.130.

Se o workflow for interrompido, o Home Assistant continua anunciando 1.12.129.
Não edite nem apague `/data`: filas, comandos, telemetria, sessões OCPP e
credenciais não participam desta atualização.

O Site 1.12.418 é o par recomendado. Os valores antigos do formulário do add-on
permanecem preservados até uma edição explícita; o novo cartão apenas aponta
desvios e não altera configuração sozinho.
