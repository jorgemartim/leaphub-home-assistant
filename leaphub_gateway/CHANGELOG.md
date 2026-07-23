## 1.12.23
- Reserva uma janela curta para comandos manuais antes da telemetria de confirmação.
- Impede que abrir/fechar ou travar/destravar em sequência fique atrás de uma leitura automática longa.
- Mantém a confirmação adaptativa em segundo plano sem transformar entrega em estado físico confirmado.

## 1.12.22
- Amplia de três para cinco as leituras adaptativas de confirmação após comandos remotos.
- Corrige instalações atualizadas que mantinham o limite legado de três leituras.
- Encerra todas as respostas privadas assinadas, eliminando timeouts ociosos após HTTP 200.
- Mantém a fila idempotente: trava, destrava, abertura e fechamento continuam sem repetição automática.

## 1.12.21

- Encerra respostas de saúde depois do envio para evitar conexões ociosas e falsos timeouts de 15 segundos.
- Mantém `confirmation_pending` coerente quando a nuvem aceitou o comando, mas a telemetria ainda não confirmou o estado.
- Preserva sessão única, idempotência, telemetria adaptativa, OCPP e diagnóstico sanitizado.

## 1.12.20

- Saúde sanitizada de Connector, OCPP e Tunnel no diagnóstico privado.
- Detecção de estado desatualizado sem exposição de logs ou identificadores.

## 1.12.19

- Mantém assinaturas habilitadas em coleta adaptativa mesmo sem nenhuma tela do Leap Hub aberta.
- Usa a janela de presença somente para aumentar temporariamente a frequência das leituras.
- Limita o intervalo econômico em segundo plano a cinco minutos por padrão para detectar viagens e recargas.
- Preserva sessão, fila SQLite, cooldown, idempotência e confirmação rápida de comandos já existentes.
- Expõe no diagnóstico se o monitoramento de fundo está ativo e corrige os textos dos intervalos padrão.

## 1.12.18.2

- Pacote de recuperação por build local, sem dependência da tag GHCR.

## 1.12.18

- Atualização rápida por imagem GHCR pré-compilada, com build local mantido em pacote de recuperação.
- Workflow com cache Buildx, autoteste e confirmação do manifesto antes de considerar a publicação concluída.
- Cloudflared deixou de ser baixado em todas as compilações e agora é preparado somente quando o túnel embutido está ativo, com SHA-256 fixo.

## 1.12.17


- Corrige o OCPP único para carregar somente o ambiente realmente ativado; o ambiente desativado não é mais consultado.
- Bloqueia configuração com Beta e Produção OCPP ativos simultaneamente, evitando eventos e comandos concorrentes.
- Usa o limite de conexões do ambiente ativo e reduz o padrão para 20.
- Reseta o backoff de reinício após cinco minutos estáveis e rotaciona logs locais para evitar lentidão e disco cheio.
- Confia em cabeçalhos de IP encaminhado somente quando a conexão veio de proxy local/privado.
- Distribui as consultas de comandos OCPP com jitter e reduz o envio de status do Gateway para cada 30 segundos.
- Preserva API v2, telemetria, 25 comandos, filas SQLite, porta pública 8092 e build local do Home Assistant.

## 1.12.16

- Reutiliza conexões HTTP(S) entre o OCPP Gateway e o Leap Hub, reduzindo DNS, TCP e TLS repetidos.
- Diferencia indisponibilidade temporária de credencial recusada durante a resolução Beta/Produção.
- Permite reconexão da mesma wallbox mesmo quando o limite de conexões está ocupado.
- Consolida Heartbeats pendentes durante indisponibilidade para evitar crescimento sem utilidade da fila.
- Tenta um único refresh de sessão também quando a leitura de mensagens detecta expiração.
- Reduz a permanência em consulta de estacionado antes do intervalo de repouso, sem alterar a confirmação de estados.
- Mantém build local do Home Assistant, API v2, OCPP 1.6, 25 comandos, SQLite e configurações existentes.

## 1.12.15.1

- Hotfix de instalação: build local pelo Home Assistant sem depender de tag GHCR ausente.
- Código funcional idêntico à 1.12.15.

## 1.12.15

- Preserva os backoffs legítimos de até 30 minutos no diário idempotente de comandos.
- Bloqueia retomadas enquanto o cooldown global da conta ainda estiver ativo.
- Executa somente um refresh lógico por falha de sessão.
- Habilita HTTP/1.1 keepalive no Connector sem alterar HMAC ou API v2.

## 1.12.14

- Mantém sessões Leapmotor saudáveis após o fim da janela ativa.
- Reduz chamadas repetidas de lista de veículos e mensagens.
- Trata expiração real de sessão com uma única reconexão coordenada.
- Detecta conexões OCPP mortas, acelera falha de comandos e aplica graça de reconexão.
- Preserva ordem e limita retenção da fila OCPP.

## 1.12.13

- Mantém integralmente os contratos, comandos, OCPP e recursos da 1.12.12.
- Remove expiração artificial de sessão e tenta refresh antes de novo login.
- Adiciona cooldown global persistente e uma única autenticação por conta.
- Deduplica assinaturas idênticas sem acordar o veículo ou alterar a agenda.
- Estabiliza estados de telemetria e aplica intervalos adaptativos de repouso.
- Corrige compatibilidade do comando de destino entre versões da biblioteca.
- Centraliza a sanitização de identificadores e segredos nos logs.
- Fecha conexões SQLite após cada operação.

## 1.12.12

- Classificação de cooldown e trava persistente contra logins automáticos repetidos.
- Recuperação automática moderada após bloqueio curto da nuvem.
- Sem mudança em comandos físicos ou OCPP.

## 1.12.11

- Volante e retrovisores aquecidos orientados por capacidade.
- Metadados completos de permissões e confirmação por telemetria.
- Sem alteração em fila, cooldown ou OCPP.

## 1.12.10

- Contrato automatizado para todos os comandos remotos.
- Testes de cooldown, redaction e pares de ações opostas.
- Sem alteração no comportamento operacional do Gateway.

## 1.12.09

- Contrato versionado, rastreabilidade e diagnóstico de compatibilidade Hub ↔ Gateway.

## 1.12.08

- Telemetria opcional de temperatura por pneu, sem estimativas.

## 1.12.07

- Prioridade manual antes do login automático e retomada idempotente após cooldown.

## 1.12.06

- Compatibilidade de migração para opções persistidas pela 1.12.04.
- O schema aceita os valores antigos para permitir a inicialização, enquanto o runtime limita a cadência aos valores seguros da 1.12.05.
- Corrige o bloqueio do Supervisor com `value must be at least 10.0`.

## 1.12.05

- Contenção de requisições, telemetria pós-comando moderada e status com backoff explícito.
- Removida a leitura extra anterior ao desligamento do clima.

## 1.12.04

- Desligamento de clima com fechamento compatível com o modo ativo e confirmação por telemetria fresca.
- Estado só é confirmado quando a leitura do veículo realmente muda.

## 1.12.03

- Corrige o diagnóstico privado OCPP, que podia falhar por chave indefinida.
- Move filas persistentes de eventos e resultados de comandos junto com o Charge ID promovido.
- Persiste resultados de comandos quando a API PHP está temporariamente indisponível.
- Reduz para 15 segundos a aplicação de rotas promovidas e suporta até 10 mil overrides.
- Reutiliza automaticamente a chave OCPP compartilhada quando preenchida em apenas um ambiente.

## 1.12.02

- Adiciona cancelamento protegido de comandos antes do envio à nuvem.
- Cancela timers de retomada e filas de autenticação sem interromper ações já iniciadas.
- Mantém o diário persistente com estado terminal `cancelled`.
- A API informa quando o comando já passou do ponto seguro de cancelamento.

## 1.11.99

- Mantém filas independentes por conta Leapmotor; uma conta não bloqueia as demais.
- Dá prioridade global aos comandos manuais sobre leituras automáticas de telemetria.
- Preserva o limite total configurado para proteger CPU, memória e a nuvem Leapmotor.
- Aceita configurações antigas de cooldown de 21600 segundos e limita o valor internamente.
- Expõe apenas contadores agregados do limitador no diagnóstico, sem e-mail, VIN ou credenciais.

## 1.11.95

- Reduz cooldown geral sem `Retry-After` de seis horas para quinze minutos, com limite máximo de uma hora.
- Reavalia cooldowns antigos excessivos em cinco minutos após a atualização.
- Mantém o bloqueio de login de dois minutos separado do limite geral da API.
- Não repete autenticação ou comando durante a pausa.

## 1.11.94

- Climatização pós-despertar com verificação fresca e uma única repetição idempotente.
- Estados de progresso não finalizam o comando antes do worker.
- Timeout temporário é verificado antes de qualquer repetição.

## 1.11.93

- Corrige `try again in 2 minutes` para cerca de 135 segundos, nunca 30 minutos ou 6 horas.
- Classifica o bloqueio diretamente no login da telemetria antes do limitador geral de API.
- Limita cooldown de autenticação a cinco minutos e mantém limites gerais separados.
- Limpa automaticamente cooldowns inválidos gravados pela 1.11.92.
- Remove o cooldown assim que uma sessão ou comando autentica com sucesso.
- Repara diários `waiting_auth` antigos para permitir retomada segura após atualização.
- Mantém VIN, PIN, senha, token e certificados fora dos logs.

## 1.11.92

- Reconhece `Password error limit has reached maximum` como bloqueio temporário, não como senha inválida.
- Extrai o prazo informado pela Leapmotor e impede qualquer novo login antes desse horário.
- Mantém o comando no estado `waiting_auth` e o retoma automaticamente após o cooldown.
- Compartilha a proteção com a telemetria para evitar logins concorrentes da mesma conta.
- Preserva credenciais, fila e sessão válida; não desconecta a conta por limite temporário.
- A resposta de status inclui contagem regressiva segura sem e-mail, VIN, PIN, token ou senha.

## 1.11.91

- Introduz o estado `sent`: a entrega termina quando a nuvem aceita a ação, enquanto a confirmação física continua separadamente.
- Evita que a tela permaneça carregando até o carro travar novamente sozinho.
- Mantém o diário idempotente: consultar `sent` nunca repete o comando.
- Climatização faz uma última leitura depois da única repetição idempotente protegida.
- Quando a nuvem aceita, mas o ar continua desligado, retorna o diagnóstico seguro `climate_not_applied_after_retry`.
- Logs distinguem envio, confirmação e estado não aplicado sem expor conta, token, VIN ou PIN.

## 1.11.90

- Detecta expiração da sessão especificamente durante `cert/sync`, antes do envio da ação.
- Descarta a sessão compartilhada inválida e faz uma única autenticação limpa para repetir o comando com segurança.
- Não repete comandos quando o erro acontece depois do possível aceite pela nuvem.
- Mantém fila prioritária e trava exclusiva por conta.
- Expõe diagnóstico seguro de recuperação de sessão sem tokens, PIN, VIN ou credenciais.

## 1.11.89

- Comandos manuais entram em fila prioritária por conta antes de aguardar a telemetria.
- Uma leitura já iniciada pode terminar, mas nenhuma nova leitura da mesma conta começa enquanto houver comando pendente.
- O comando não falha mais após 60 segundos: aguarda a conta por uma janela protegida de até 180 segundos.
- A vaga global do Connector só é ocupada depois que a conta fica livre, evitando bloquear outras contas.
- Logs registram tempo de fila e tipo seguro do ocupante da conta, sem e-mail, VIN, PIN ou credenciais.
- Novos estados `waiting_account` e `waiting_slot` distinguem fila da conta e fila global.

## 1.11.88

- Corrigido logger indefinido no caminho de verificação do comando remoto.
- O tratamento de erro de confirmação não pode mais gerar uma segunda exceção.
- Climatização repete uma única vez a ação idempotente quando o carro acorda, mas a leitura direta falha.
- Logs preservam o erro original sem expor credenciais, VIN ou PIN.

## 1.11.87

- Sessão Leapmotor reutilizada entre telemetria e comandos sob trava por conta.
- Removido o encerramento preventivo que provocava nova validação antes do comando.
- Cache da última lista válida de veículos para resolver o VIN sem chamada adicional.
- Estado `cloud_accepted` somente após a ação realmente ser enviada.
- Persistência de nonce com WAL, busy timeout e novas tentativas limitadas.

## 1.11.86

- climatização verifica uma leitura fresca e pode repetir uma única vez somente `climate_on`/`climate_off`;
- comandos confirmados diretamente passam a `completed`;
- janela de telemetria de comando ampliada para 180 segundos;
- logs distinguem envio, retry idempotente, confirmação direta e confirmação por telemetria;
- telemetria registra quando o veículo-alvo não aparece na assinatura.

## 1.11.85

- elimina a disputa de SQLite causada por `PRAGMA journal_mode` e criação de tabelas em cada consulta de comando;
- adiciona cache idempotente em memória com persistência best-effort para status de comandos;
- impede `BrokenPipeError` de virar falso HTTP 500 quando o Cloudflare encerra uma conexão;
- reduz a latência da proteção anti-replay e mantém segurança em memória durante lock temporário;
- usa resumo de saúde não bloqueante para não derrubar o watchdog durante uma coleta;
- adiciona protocolo configurável do Cloudflare Tunnel e usa HTTP/2 por padrão em redes com QUIC instável.

## 1.11.84

- Corrigida concorrência do SQLite durante a inicialização do Connector.
- Painel passa a respeitar a janela de migração e usa conexão somente leitura.
- Migração de journal agora é idempotente e tolera travas curtas.

## 1.11.83

- Corrige `sqlite3.OperationalError: unable to open database file` na fila persistente.
- Migra o SQLite de WAL para journal tradicional, adequado ao acesso serializado do Gateway.
- Valida escrita e permissões em `/data/telemetry` antes de iniciar.
- Adiciona recuperação automática e recuo progressivo, eliminando tempestade de logs.
- Expõe saúde do armazenamento no diagnóstico do Connector.
- Repassa `telemetry_command_max_polls` e corrige o padrão estacionado para 300 segundos.

## 1.11.82

- Comando direto primeiro: o próprio endpoint remoto tenta acordar e executar, como no aplicativo oficial.
- Despertar separado somente após resposta explícita de veículo dormindo ou offline.
- Sessão limpa entre o despertar e a ação para evitar que o token de wake invalide o comando.
- Estados persistentes de fila, preparação, despertar, reconexão, execução e confirmação.
- Telemetria pós-comando liberada poucos segundos após a ação, sem esperar o ciclo normal.
- Nenhum comando ambíguo é reenviado automaticamente.

## 1.11.81

- Comandos remotos entram em fila prioritária e retornam imediatamente ao Leap Hub.
- Execução continua em segundo plano com trava por conta, idempotência e diário persistente.
- Novo endpoint protegido permite acompanhar processamento, sucesso ou falha sem reenviar a ação.
- Telemetria cede a conta enquanto houver comando pendente e retoma após estabilização.
- Reinício do App não autoriza repetição automática de um comando ainda indefinido.

## 1.11.80

- Trata perda de token somente na consulta do resultado como comando já aceito, sem reenviar a ação.
- Aguarda a estabilização da sessão antes de retomar telemetria após comandos remotos.
- Telemetria cede a conta em pontos seguros quando existe comando manual aguardando.
- Reduz o timeout das leituras automáticas e amplia a espera do comando manual.
- Remove VIN e valores criptográficos dos logs e higieniza registros antigos.
- Adiciona diário persistente por identificador de solicitação para impedir repetição após perda da resposta HTTP.

## 1.11.79

- Corrige comandos remotos que recebiam `car_id` no lugar do VIN e terminavam em HTTP 422.
- Aceita VIN protegido enviado pelo Leap Hub e mantém compatibilidade com instalações antigas resolvendo `car_id` internamente.
- Encerra a sessão automática antes do login manual, evitando dois tokens sobrepostos e respostas `Information verification failed`.
- Registra a causa sanitizada de erros 422 sem expor VIN, PIN, senha, certificados ou chaves.
- Mantém confirmação adaptativa e proteção contra comandos duplicados.

## 1.11.78

- Confirmação de comandos com cadência adaptativa em 3, 6, 10 e 15 segundos.
- Encerra a janela rápida quando o estado esperado é confirmado ou quando o orçamento seguro é atingido.
- Comandos manuais recebem prioridade sobre telemetria automática.
- Consultas de confirmação ficam limitadas ao veículo afetado e não carregam mensagens da conta.
- A sessão automática é renovada de forma controlada após um login manual, evitando conflito de token.

## 1.11.77

- Comandos remotos tentam acordar o veículo antes da execução quando a biblioteca instalada oferece essa função.
- O próprio comando continua sendo enviado quando não existe um método de despertar separado, porque a nuvem pode acordar e executar na mesma chamada.
- Repete apenas respostas explícitas de veículo dormindo, offline ou ainda não pronto; timeouts ambíguos não são repetidos para evitar comandos duplicados.
- Cria uma janela de confirmação de 90 segundos com leitura a cada 3 segundos após um comando remoto.
- Corrige o repasse das opções de janela interativa, presença e confirmação de comando ao processo de telemetria.
- A janela de confirmação continua ativa mesmo quando o usuário fecha ou troca de tela.
- Mantém os intervalos adaptativos normais fora dessa janela para reduzir risco de limitação da conta.

## Hotfix de sessão e OCPP 1.11.75

- Corrige status OCPP e reduz recriações de sessão durante navegação.
- Protege a conta Leapmotor com backoff conservador.

## Presença e timeout 1.11.75

A janela interativa encerra ao fechar a última aba. Timeouts temporários preservam a sessão e usam repetição curta protegida, sem novo login imediato.

## 1.11.75

- Segurança: nonce HMAC persistente, telemetria iniciada uma única vez e estado explícito de reautenticação.

- Telemetria interativa com sessão reutilizada e encerramento automático.
- Heartbeat de leitura confirmado durante a presença do usuário.
- Correção do mapeamento entre porta do motorista e camadas de vidros.

## 1.11.71

- Sessões Leapmotor agora possuem trava isolada por conta.
- Contas diferentes podem usar o paralelismo configurado sem ficarem bloqueadas por uma chamada lenta de outra conta.
- Upsert, remoção, expiração e coleta continuam impedidos de fechar a mesma sessão durante uma leitura.
- Mantida uma única tentativa de login por ciclo, cooldown persistente e bloqueio compartilhado com operações manuais.

## 1.11.70

- A telemetria só consulta a Leapmotor durante uma janela ativada pela presença do usuário no Leap Hub.
- A sessão autenticada é reutilizada; não existe mais um novo login em cada ciclo de coleta.
- Cada operação cria no máximo uma tentativa de login e falhas usam espera progressiva de 5 min até 6 h.
- Falha de autenticação pausa a assinatura até nova confirmação das credenciais.
- Reenvios com as mesmas credenciais não removem a proteção de autenticação ou cooldown.
- Limite de requisições ativa cooldown padrão de 6 horas.
- Intervalos seguros: 30 s dirigindo/carregando, 5 min estacionado e 15 min em repouso.
- Quando a janela de presença termina, a sessão é encerrada e nenhuma consulta à nuvem continua.
- Sincronização manual e telemetria compartilham o mesmo lock por conta, impedindo logins paralelos.
- As opções `connector_max_parallel` e `connector_manual_wait_seconds` passam a ser aplicadas corretamente.

## 1.11.69

- Reconexão automática de sessão/token da Leapmotor.
- Bloqueio por conta contra chamadas simultâneas.
- Falhas temporárias retornam 503 e entram em recuperação automática.
- A credencial só é indicada para revisão quando a reautenticação é realmente recusada.

## 1.11.67

- Canvas oficial preservado e animação de carregamento.
- Teste de imagens por veículo acionado pelas Configurações do Leap Hub.

## 1.11.67

- Envia uma galeria sanitizada das camadas oficiais recebidas da API para diagnóstico administrativo.
- Inclui prévias transparente, branca e escura da mesma composição.
- Limita quantidade, resolução e tamanho total das imagens de diagnóstico.
- Não envia VIN, conta, token, certificado, chave privada nem payload bruto.
- Contrato oficial de renderização versão 12.

## 1.11.65

- Corrige a camada de vidro fechado quando a porta correspondente está aberta.
- Achata a composição oficial em fundo branco para eliminar artefatos de transparência no tema escuro.
- Só exibe cabo/carregamento sem sensores AC/DC quando existe potência externa real.
- Mantém biblioteca por assinatura visual e cache isolado por estado.
- Contrato de renderização oficial versão 11.

## 1.11.64

- Corrige composição oficial, transparência e consistência entre porta/vidro e imagem.
- Impede que leitura parcial feche visualmente uma abertura ainda ativa.

## 1.11.63

- Usa o pacote oficial de imagens da API para compor localmente modelo, cor, portas, vidros, porta-malas e carga.
- Envia somente WebP final, hash e metadados seguros; não envia ZIP, chave do pacote, VIN ou credenciais.
- Corrige falso carregamento cruzando conector rápido/lento, estado plugado, potência e movimento/regeneração.
- Atualiza o contrato visual para a versão 7.

## 1.11.62

- Publica o contrato visual versão 6 com estado explícito `true`, `false` ou desconhecido por componente.
- Lista componentes conhecidos, desconhecidos e ativos sem interpretar ausência como fechado.
- Permite ao Leap Hub usar o contrato como fallback quando a estrutura detalhada do sensor vier incompleta.
- Inclui o contrato na fingerprint sem adicionar VIN, localização, credenciais ou identificadores da conta.
- Preserva fila ordenada, deduplicação semântica e heartbeats.
- Atualiza a versão do mapeamento para 1.11.62.

## 1.11.61

- Publica o estado visual versão 5 com pistas seguras de resolução do modelo e da cor.
- Informa a origem dos campos usados e se a imagem HTTPS reportada pela nuvem estava disponível.
- Adiciona avisos de identidade e lista dos grupos de sensores com cobertura incompleta.
- Mantém VIN, credenciais, localização e identificadores da conta fora do diagnóstico visual.
- Preserva fila ordenada, deduplicação semântica e heartbeats da versão anterior.
- Atualiza a versão do mapeamento para 1.11.61.

## 1.11.60

- Publica o estado visual versão 4 com diagnóstico de cobertura dos sensores.
- Separa a fingerprint do estado da fingerprint da amostra, evitando atualizações visuais desnecessárias.
- Ordena eventos por veículo e impede que uma leitura nova ultrapasse outra pendente.
- Suprime leituras semanticamente idênticas e mantém heartbeats seguros conforme o estado do carro.
- Adiciona sequência, tipo do evento e indicador de alteração real ao payload entregue.
- Mantém a última leitura no site quando o Home Assistant fica temporariamente indisponível, sem inventar dados.
- Atualiza a versão do mapeamento para 1.11.60.

## 1.11.59

- Atualiza a representação do veículo em tempo real sem recarregar a página inteira.
- Publica o estado visual versão 3 com identidade do modelo, cor, horário e fingerprint determinístico.
- Adiciona climatização, pré-aquecimento da bateria, carga concluída e retrovisores recolhidos aos componentes visuais.
- Mantém o payload sem VIN, credenciais ou identificadores de conta dentro da assinatura visual.
- Atualiza a versão do mapeamento para 1.11.59.

## 1.11.58

- Gera uma assinatura visual determinística para cada combinação de estado do veículo.
- Informa quais sensores de portas, vidros, teto, luzes e segurança realmente responderam.
- Diferencia estado fechado de estado não informado, evitando alertas falsos na interface.
- Prepara imagens completas e camadas transparentes por modelo, cor e componente.
- Atualiza a versão do mapeamento para 1.11.58.

## 1.11.57

- Envia `outColor` para o Leap Hub e preserva aliases de cor encontrados no retorno bruto.
- Amplia o estado visual com portas, vidros e percentuais individuais, teto solar, cortina, luzes, espelhos, sentinela e segurança.
- Envia climatização avançada, bancos, volante aquecido, conectividade, plano de carga, tipo de conector, tempo restante e estado dos pneus.
- Mantém compatibilidade com leituras antigas e com campos ausentes por modelo ou permissão.
- Atualiza a versão do mapeamento para 1.11.57.

## 1.11.56.1

- Corrige a inclusão e a importação do motor de telemetria na imagem publicada.
- Instala o módulo também em site-packages com nome interno exclusivo.
- Adiciona teste de runtime da imagem exata antes da publicação no GHCR.
- Mantém configurações, fila persistente, OCPP e Tunnel sem alteração.

## 1.11.56.1

- Corrige `ModuleNotFoundError: No module named leaphub_connector/connector`.
- Instala o Connector em `site-packages` com nome interno exclusivo.
- Adiciona autoteste obrigatório de importação na compilação Docker.
- Adiciona validação de presença e tamanho do arquivo `connector.py`.
- Registra no log o caminho do módulo carregado antes de iniciar os serviços.

## 1.11.54.2

- Dockerfile reorganizado para preservar o cache das camadas pesadas em compilações locais.
- Limites de conexão e tempo no download do Cloudflared.
- Correção da biblioteca compartilhada do Python.

## 1.11.54.1

- Migração para a imagem oficial `base-python` do Home Assistant.
- Correção do erro `libpython3.12.so.1.0`.

## 1.11.54

- App único para Connector, OCPP Beta, OCPP Produção e Cloudflare Tunnel.
- Painel Ingress responsivo com saúde, PID, reinícios, testes e logs recentes.
- Supervisão individual dos processos.
- Token do Tunnel fora da linha de comando.
- Migração reversível.
- Ícone, logotipo, traduções, documentação e política AppArmor.

## 1.11.76

- Corrige a classificação de `Failed to issue certificate`: falha temporária da nuvem não bloqueia mais a conta como senha incorreta.
- Permite limpar com segurança um `auth_required` preso quando o Leap Hub comprova uma sincronização manual bem-sucedida.
- Corrige a composição oficial do veículo com portas abertas, removendo o reflexo do vidro fechado que aparecia deslocado na frente da porta.

## 1.12.18.2
- Recuperação por build local quando a imagem GHCR não estiver publicada.
