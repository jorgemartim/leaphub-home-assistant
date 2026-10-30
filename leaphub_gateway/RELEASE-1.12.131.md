# Gateway 1.12.131 — histórico de recargas para conferência

Base: 1.12.130 (`21227f2f8b7d3c087b4cf6e3c8fc521f1b13a4de`). Preparado para revisão; a imagem não foi publicada nem instalada.

O novo endpoint HMAC `/v1/vehicles/charging-record` estende o caminho de leitura de baixa prioridade que já serve às estatísticas Official. Reutiliza conta/cliente autenticados, escopo de ambiente/assinatura, trava da conta, slot global, trava da sessão e checagem do alvo depois das travas. Um comando pendente tem prioridade. O teto de rede continua em quatro segundos e o timeout do cliente é restaurado no fim.

Uma solicitação realiza no máximo um POST para `/carownerservice/charge/daily/detail/page`. O VIN vem exclusivamente do veículo autorizado em cache. A janela tem até sete dias; o offset é explícito; cada página tem 25 registros e só páginas 1–5 são aceitas. Não há login, refresh de token, wake-up, retry ou comando de controle.

O retorno usa um contrato próprio `probe_kind=charging_history`, schema 1, fonte `leapmotor_cloud` e unidade `kWh`. Só são enviados horários epoch em milissegundos, tipo AC/DC/desconhecido e energia `chargeInEnergy`; VIN, coordenadas, mensagens e campos extras não são repassados. Registros inválidos são contados, intervalos sem sobreposição são descartados e cruzamentos de borda são sinalizados sem ratear energia. Lista ausente/formato incompatível não se transforma em zero.

O histórico de viagens preserva seu contrato anterior. A biblioteca continua em 0.3.2, que já expõe o endpoint; comandos, detecção, credenciais e bancos não foram migrados.

Este recurso é consumido pelo Site Beta 1.12.447 em uma ação explícita de conferência. Não importa nem substitui automaticamente recargas, faturas ou cálculos locais. A versão anterior do Gateway continua compatível com os fluxos anteriores do site; a nova leitura exige esta revisão.

A referência anterior ao diagnóstico que chamava métodos sem VIN/datas descreve a rotina CLI legada `handle_driving_record`. O endpoint HTTP atual da 1.12.130 já usava uma leitura protegida de estatísticas de viagens; foi esse caminho que estendemos, sem reativar o login separado da rotina antiga.

Validação em ambiente isolado e com clientes/contas fictícios. Não houve autenticação na conta real, consulta à nuvem real, comando físico, publicação GHCR ou instalação no Home Assistant. A validação de formatos reais por modelo ainda é necessária depois de publicar a imagem.

Apenas uma branch de revisão deve ser publicada nesta etapa. Mesclar em main dispara o workflow de build/publicação; config.yaml só será promovido depois da validação da imagem e do pull anônimo pelo fluxo existente.
