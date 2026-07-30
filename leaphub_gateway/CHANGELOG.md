## 1.12.61

Distribuição pré-compilada preservada, com publicação em duas fases.

### A confirmação de comando volta a funcionar

A confirmação nunca concluía: todo comando terminava em `amostras avaliadas=0`, inclusive os que executavam de fato no carro. A 1.12.60 instalou a medida do atraso e a resposta veio da produção, num host em `-03:00`:

```
Confirmação inconclusiva de sunshade_open: amostras avaliadas=0,
descartadas por idade=1, amostra mais recente 10739s antes do comando
```

Três comandos consecutivos, com 2 minutos entre eles, relataram **10739s, 10740s e 10777s**. Atraso real cresceria junto com o intervalo; deslocamento fixo não cresce. Eram 3 horas exatas — o offset do fuso do host.

- **Causa:** `captured_at` chega **sem fuso** quando a nuvem informa `collectTime`. A `leapmotor_api` faz `datetime.strptime` (ingênuo, com `noqa: DTZ007` no próprio código dela) e o connector serializava com `isoformat()` cru. O portão de frescura presumia UTC, deslocando o carimbo pelo offset do host e descartando 100% das amostras.
- **O site sempre esteve certo:** ele lê o mesmo campo com `strtotime()`, que interpreta string sem fuso no fuso do servidor, e por isso exibia a idade correta ("Há 4 min") e atualizava a figura do carro. Só a comparação da confirmação divergia.
- **Correção na origem:** `iso_timestamp()` passa a anexar o fuso local a datetime ingênuo, para nenhum consumidor precisar adivinhar.
- **Correção na leitura:** carimbo sem fuso passa a ser lido como hora local. Frescura e atraso passaram a derivar de um único `_command_sample_epoch()` — antes eram dois blocos de parsing duplicados que podiam divergir.
- **Guarda de direção:** amostra mais de 15 min no futuro não confirma nada. Se algum dia o carimbo vier mesmo em UTC, presumi-lo local o jogaria ~3h à frente, e é melhor não confirmar do que confirmar com carimbo impossível. Adiantamento pequeno do relógio da nuvem (~1 min, observado) continua tolerado.

### Mantido da 1.12.60

- As chaves observadas na telemetria são registradas para qualquer amostra, antes do descarte por idade — antes ficavam dentro do ramo `if not evaluable` e o log dizia `chaves=[nenhuma]` quando o caso era só atraso.
- A linha de confirmação inconclusiva informa a distância entre a captura e o envio.

### Sem alteração

- A matriz de comandos, o conjunto de campos de confirmação e a janela FAST seguem idênticos. Nenhuma mudança em credenciais, OCPP, MQTT, schema, migrations ou dados existentes.
- A margem de 2s da frescura não mudou de valor; mudou de lugar, para dentro do cálculo do atraso.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com promoção somente após validação pública da imagem.
