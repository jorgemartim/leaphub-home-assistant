# Gateway 1.12.135 — contrato da consulta de recargas

Base publicada 1.12.134. config.yaml continua anunciando 134 até o workflow oficial construir, testar e verificar a imagem 135. A revisão não foi instalada no Home Assistant do usuário.

O usuário confirmou que seu histórico aparece no aplicativo oficial. A consulta do Gateway recebeu HTTP 200 e código de negócio 39. A rotina anterior reproduzia o contrato do SDK 0.3.2: datas AAAA-MM-DD, timeZone e paginação numérica no JSON. A implementação pública atual de histórico do Mate envia segundos Unix como strings e paginação como strings, sem timeZone. Referência: ProtossBlaster/leapmotor-mate, commit 18c0be1, poller/mate_api_runtime/history_worker.py. Suas notas v4.3.0 também relatam código 39 em uma falha de assinatura; isso é pista pública, não prova da causa específica nesta conta.

O caminho autenticado do Gateway passa a usar epoch_seconds. A assinatura é calculada sobre os mesmos valores enviados no corpo. Mantém uma única chamada por consulta, sessão/certificado existentes, travas, prioridade da telemetria e dos comandos e timeout limitado. Não faz login, refresh, retries nem fallback automático. O perfil sdk_dates permanece para comparação offline dos contratos existentes.

Para o perfil atual, code/result presentes precisam ser inteiros zero consistentes, com data.list válida. result=0 isolado, booleanos, código de recusa ou conflito continuam falhando. Datas chargeEarliestTs/chargeLatestTs são aceitas como período de carga; na ausência delas, usa os campos antigos da conexão. FAST/SLOW e 1/2 são reconhecidos. Registros declarados de outro VIN são descartados. Só saem horários, energia, tipo e contagens; sem corpo bruto, credenciais, VIN ou coordenadas.

Testes usam o transporte/parser reais do SDK fixado com HTTP sintético, recomputam HMAC sobre os campos enviados, comprovam uma chamada, ausência de login/refresh, aceitação de lista vazia explícita, recusa de respostas inválidas e exclusão de outro veículo. A suite canônica é executada separadamente.

Limitação: não implementa o cliente independente nem a autenticação versão 2 usada por outra implementação. O formato novo é uma correção verificável de compatibilidade, não comprovação de que o código 39 acabou na conta real. Após construir/publicar/instalar 135, uma consulta explícita no Beta ainda é necessária para homologar. Nenhuma energia local é importada ou alterada por esta consulta.
