# Gateway 1.12.133 — leitura e classificação do conteúdo das recargas

Base publicada: 1.12.132. Compatível com o Site Beta 1.12.449, sem novo ZIP do site.

O caso recebido agora é charging_response_invalid, HTTP da nuvem 200 e nenhum código reconhecido. Isso não comprova recarga vazia, recusa de credenciais ou conta compartilhada: a representação do conteúdo ainda não foi identificada no log anterior.

Foi reproduzida uma incompatibilidade concreta do leitor fixado: json.loads() sobre texto com BOM UTF-8 lança erro antes de ler o JSON. A revisão remove somente um BOM inicial, depois exige os mesmos HTTP 200, código 0, objeto data.list e campos válidos já exigidos. Erro com BOM continua erro; HTML, JSONP, XML, JSON escalar e JSON embutido em HTML não são aceitos como histórico. Não foi confirmado que o conteúdo real deste veículo tem BOM; esse caso é coberto e testado, sem ser atribuído à conta real.

Em falha, um perfil seguro identifica JSON objeto/lista/escalar/nulo, HTML, markup, texto não JSON, conteúdo vazio/ausente e resposta acima de 2 MiB. MIME é reduzido a json/html/text/other/missing; tamanho usa faixas; somente presença de sete chaves conhecidas e estado HTTP inteiro limitado do envelope podem sair do leitor. Não entram corpo, cabeçalhos brutos, URL de redirecionamento, campos desconhecidos, VIN, credenciais ou hash do conteúdo.

O log do leitor inclui esses tipos e códigos. Os adiamentos anteriores à leitura também registram o motivo fechado, para distinguir fila, sessão, prioridade e pausa de proteção. Não há consulta automática, login, refresh, retry ou comando de controle. Endpoint, datas, fuso, assinatura, limites de páginas e filtragem do intervalo não foram mudados. Leituras de viagens continuam com seu contrato anterior, e a consulta nova permanece somente no Beta.

## Conferência da biblioteca

Revisada a main pública 0.6.0, commit 22593b496a99fea5b7d759611935fea63f75edd8: o endpoint de charging daily detail e o parser base são iguais aos usados da 0.3.2. Trocar a dependência por si só não explica nem corrige HTTP 200 sem código reconhecido. A dependência permanece em 0.3.2.

A issue pública #27 (19/10/2026) e a PR #28 relatam SLOW/FAST, paginação e histórico vazio para conta compartilhada em B10. O exemplo compartilhado é JSON com code 0 e data.list vazia, diferente da evidência atual. Esses relatos não foram usados para concluir que esta conta é compartilhada nem para remapear dados do C10 sem uma resposta válida.

Fontes: https://github.com/markoceri/leapmotor-api/blob/22593b496a99fea5b7d759611935fea63f75edd8/src/leapmotor_api/client.py ; https://github.com/markoceri/leapmotor-api/issues/27 ; https://github.com/markoceri/leapmotor-api/pull/28 . São documentação e relatos da comunidade, não uma garantia de suporte por modelo/região.

## Entrega e limites

Imagem pré-compilada distribuída pelo workflow oficial: config.yaml permanece anunciando 1.12.132 até build, testes da imagem e acesso público ao GHCR serem confirmados. Testes usam transporte/parser reais da biblioteca e respostas sintéticas, sem login ou comandos. Ainda é necessário verificar o conteúdo real com a nova leitura; não se afirma que o problema do serviço remoto foi resolvido. Não há alteração de kWh, faturas, dados históricos, produção do site ou instalação remota no Home Assistant. Logs e identificadores recebidos do usuário não são publicados.
