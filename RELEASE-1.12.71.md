## 1.12.71

Distribuição pré-compilada preservada, com publicação em duas fases.

Uma release pequena, e ela existe porque a 1.12.70 comprou uma coisa pagando com
outra. Conserta o preço.

### O que a 1.12.70 fez, e o que isso custava

A causa 3 daquela release era real: o cliente Leapmotor da sessão persistente é o
**mesmo** que despacha os comandos, e nascia com o tempo limite da telemetria
(15 s), enquanto o despacho mais lento medido — `sunshade_position` — levou
**12,686 s**. Folga de 2,3 s.

O conserto foi elevar o tempo limite do **cliente inteiro** para um piso de 25 s.
Ele resolve o despacho, mas o mesmo cliente faz a leitura de telemetria — e é a
leitura que **segura a trava da conta** durante a chamada. Alongar a leitura
alonga a espera de quem manda o comando seguinte.

Isso não é hipótese: é a **causa 4** dos mesmos logs de 02/08/2026, e ela já
doía antes de a 1.12.70 existir.

```
14:02:23  Comando cd604eea3941 aguardando conta há 15s; ocupante=leaphub-telemetry-poll_0
14:02:38  Comando cd604eea3941 aguardando conta há 30s; ocupante=leaphub-telemetry-poll_0
14:02:46  sunshade_close ... espera_fila=36s, latência_conta=36202ms, total=38384ms
```

O despacho em si levou 2,1 s dos 38,4 s. Os outros 36 s foram espera pela trava.
A 1.12.70, deixada como estava, aumentaria o teto dessa espera em dois terços — e
a presença `interactive` que o site 1.12.301 ligou faz a telemetria consultar com
mais frequência, ou seja, aumenta também a chance de colidir.

### O conserto: emprestar em vez de gravar

A biblioteca lê `self.timeout` **na hora da chamada**, não na construção — os
quatro pontos de `timeout=self.timeout` em `client.py`. Então os segundos a mais
podem ir só para quem precisa deles:

- o cliente volta a **nascer** com `telemetry_request_timeout_seconds`;
- `execute_command` envolve o despacho em `_dispatch_timeout(client)`, que eleva
  o valor ao piso de 25 s e o **devolve no `finally`** — inclusive quando o
  despacho levanta.

Quem configurou mais que 25 s continua com o que configurou: é piso, não valor.
E o empréstimo respeita o mesmo teto de 45 s que `connector.create_client`
aplica.

Seguro contra concorrência porque todo o trecho roda dentro de
`_session_operation_lock(subscription_id)`, e cada assinatura tem o seu cliente.
Se uma biblioteca futura não expuser `timeout`, o gerenciador não faz nada e o
despacho corre como antes — nunca quebra.

### O que continua aberto na causa 4

Emprestar o tempo limite **limita** o quanto a leitura pode segurar a trava; não
elimina a colisão. O caminho para eliminá-la seria a telemetria ceder a trava no
meio de uma chamada em andamento, e não dá: uma leitura HTTP bloqueada não é
interrompível sem fechar o socket. Os pontos de cedência que existem hoje
(`manual_should_yield`) ficam **entre** chamadas, e é por isso que a espera
medida foi de ~36 s: dois tempos limite de 15 s mais a retentativa interna da
biblioteca.

Reduzir isso de verdade é decisão de produto — trocaria frescura de telemetria
por latência de comando —, e por isso não entra numa release de conserto.

### O contrato

`test_command_window_backoff_1_12_70` ganha o teste do empréstimo, com dublês:

- o despacho corre com o piso e o cliente volta ao valor da telemetria;
- **o mesmo vale quando o despacho levanta** — senão a leitura seguinte
  seguraria a trava por mais tempo, que é exatamente o que esta release existe
  para impedir;
- quem configurou mais continua com o que configurou;
- biblioteca sem o atributo `timeout` não quebra o despacho;
- e a asserção que a 1.12.70 fazia sobre `_create_persistent_session_locked`
  passa a ser a **negação** dela: o piso não pode voltar a ser gravado no
  cliente.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- Nenhuma mudança na matriz de comandos, na cadência da janela de confirmação ou
  no casamento das esperas — tudo o que a 1.12.70 consertou fica como está.
- `Dockerfile` intocado.
- `config.yaml` intocado: o CI o promove depois de a imagem ficar pública.
