# Leap Hub Gateway 1.12.78

## O Gateway termina e avisa; antes ele terminava e esperava ser perguntado

Teste ao vivo em 12/08/2026, conta `acct_1c8b987d`, comando `unlock`:

```
09:21:25    site despacha; Gateway aceita (POST /v1/vehicles/command -> 200)
~09:21:28   o carro destrava fisicamente (~3s, o dono estava à vista)
09:21:31,9  worker TERMINA: espera_fila=0s, latência_conta=1ms,
            dispatch=6171ms, total=6180ms, ack=library_returned,
            resultado_remoto=completed, sinal=positive
09:22:07    site ainda stage: executing, cloud_accepted: false
09:22:31    site enfim stage: sent, cloud_accepted: true
```

Carro **3s**. Gateway **6,2s**. Tela **41-65s**.

O navegador não estava parado: ele perguntava a cada 4-6s
(`poll_after_seconds` 6, depois 4) e recebeu `executing` nas ~10 vezes. Não
havia o que ler. O desfecho existia apenas dentro deste Gateway, e o site só ia
buscá-lo na volta seguinte do ciclo do cron.

O gargalo nunca foi a nuvem, nem o carro, nem a trava da conta. Era o site
**descobrir** que o worker tinha terminado.

## O que mudou

Ao concluir o worker, o Gateway faz um POST assinado em
`/api/internal/commands/result` no site, com o mesmo payload que
`/v1/vehicles/command/status` devolveria. O poll de 4-6s do navegador, que já
existia e já era barato, passa a encontrar o resultado logo na pergunta
seguinte.

O destino é **derivado** da URL de telemetria já configurada, trocando só o
sufixo da rota. Nenhuma opção nova precisa ser preenchida na instalação de
campo — e isso não é conveniência, é a mesma razão de sempre: opção gravada em
instalação existente não relê padrão novo.

## O que ele deliberadamente NÃO faz

**Não usa a conexão da thread de entrega.** Reaproveitar `_post_delivery`
custaria o `_delivery_guard`, e o anúncio ficaria atrás de um lote de telemetria
— exatamente a fila que ele veio desfazer. Ele abre a própria conexão, curta, e
fecha.

**Não segura o worker.** Sai em thread daemon, porque neste ponto o worker ainda
precisa liberar a trava da conta e a vaga do connector. Um site lento não pode
atrasar o *próximo* comando do dono. O anúncio é atalho, não etapa.

**Não insiste.** Timeout de 8s, sem retry. 404 (site anterior à rota), queda de
rede ou destino fora do formato conhecido devolvem `False` em silêncio. O ciclo
do cron continua sendo a rede de segurança, e nenhuma falha do atalho pode
derrubar um worker que já concluiu o comando com sucesso.

## Uma fonte só para o payload

`command_journal_finish` passou a **devolver** o dicionário que grava no diário.
Sem isso, o anúncio teria que remontar o payload por conta própria, e push e
cron passariam a produzir estados diferentes para o mesmo comando. O contrato
compara os dois lados campo a campo.

## O outro lado, que explica os 41-65s

Vale registrar por que o poll do navegador não resolvia sozinho. No site, o
endpoint lido pela interface é passivo de propósito desde a 1.12.237, com a
justificativa de que "o Worker já consulta o Gateway no fast loop de três
segundos". Esse worker não existe mais: `workerStatus()` devolve `pid` fixo em
`null`, e quem escreve o heartbeat que o declara vivo é o **próprio ciclo do
cron**. Com o cron a cada ~55s, o site se considera saudável e permanece
passivo — esperando um laço de 3s que nenhum shell executa.

Reintroduzir consulta síncrona ali seria repetir um erro já pago: foi ela que
prendeu o poll da interface por 14,8s. O anúncio resolve pelo lado certo — o
dado chega ao site sozinho, e o poll continua local e barato.

## Prova

`tests/test_command_announce_1_12_78.py`, com controle negativo em cada garantia:

- o anúncio vai para a rota de comando e é assinado **para aquele caminho** — a
  mesma assinatura não vale para o caminho da telemetria, que é justamente o que
  o site confere;
- a conexão da thread de entrega continua intocada depois do anúncio;
- 404, erro de transporte, destino não derivável, `request_id` vazio e resultado
  vazio devolvem `False` sem levantar exceção;
- o payload anunciado é campo a campo o que `command_journal_status` serve.

Verificado por mutação: trocar o sufixo da rota reprova o primeiro contrato;
fazer o diário devolver a resposta crua em vez do payload gravado reprova o
último.
