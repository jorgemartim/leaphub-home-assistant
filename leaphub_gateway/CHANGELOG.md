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
