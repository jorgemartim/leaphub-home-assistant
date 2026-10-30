# Gateway 1.12.134 — erros result/message do histórico de recargas

Base publicada 1.12.133. Compatível com o Site Beta 1.12.449, sem novo ZIP.

Uma resposta de recargas foi identificada como objeto JSON, com as chaves result e message, sem code ou data. O MIME declarado era HTML, mas o conteúdo era JSON. Isso descarta BOM neste caso, mas não informa os valores desses campos nem comprova a causa da recusa. Não foi confirmado que a API oferece este histórico para todos os modelos e regiões.

O tratamento anterior só extraía o código de code. Agora, somente em falhas e quando code está ausente, um result numérico limitado pode ser mostrado como código da nuvem. Booleanos, objetos, números fora do limite e texto arbitrário não viram códigos. A presença de code conserva sua precedência. Não há novo caminho de sucesso: result 0 sem code 0 e data.list válidos continua rejeitado.

Mensagens conhecidas geram apenas uma categoria fechada: auth, access, signature, route, request, temporary, missing, empty ou unrecognized. Nenhum texto da mensagem é retornado ou registrado. Essa classificação é uma pista de erro, não prova de suporte do endpoint ou causa definitiva. Mensagens de acesso, autenticação e indisponibilidade já podem aparecer com seus avisos locais correspondentes no site 449. As demais falhas preservam o aviso de recusa ou formato inválido.

O log acrescenta resultado numérico limitado e mensagem_classe. Não expõe corpo, mensagens externas, cabeçalhos, VIN, localização ou credenciais. Os testes usam respostas sintéticas com transporte e parser reais da biblioteca fixada. Nenhum log do usuário foi publicado.

Endpoint, datas, fuso, assinatura e dependência 0.3.2 permanecem iguais. A consulta continua uma única leitura no Beta, reutilizando a sessão e as travas existentes, sem login, refresh, retries, comandos ou alterações no histórico de energia. Não se afirma que esta revisão recupera os registros que a nuvem não retornou. A próxima consulta ainda é necessária para identificar o código ou categoria da resposta real.

A imagem só é anunciada em config.yaml após a construção, os testes da imagem e a verificação de acesso público no workflow oficial. Publicar a imagem não instala a atualização no Home Assistant do usuário.
