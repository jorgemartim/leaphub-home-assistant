## 1.12.72

Distribuição pré-compilada preservada, com publicação em duas fases.

Uma leitura de **diagnóstico**, e nada mais. Ela não muda cadência, não muda
comando, não liga nada sozinha.

### O buraco que ela existe para medir

A telemetria ao vivo só enxerga o que o carro subiu para a nuvem — e o carro
para de subir enquanto roda.

Medido em 31/07/2026, numa viagem de 94 km: das **112 leituras** registradas,
**72 eram a mesma**. O Gateway perguntou 72 vezes ao longo de 71 minutos e a
nuvem devolveu sempre o mesmo instantâneo, com o mesmo carimbo de hora e a mesma
velocidade congelada, enquanto **60 km** eram percorridos. Numa outra viagem do
mesmo dia foram **320 cópias** da mesma leitura em 5h40.

Não é defeito do Gateway nem do site: é o carro que silencia. As cópias são a
prova de que o Gateway continuou perguntando. Nenhuma mudança de cadência
resolve — não há o que buscar.

Consequência prática: a média de velocidade do site não tem como bater com o
computador de bordo, porque o trecho de rodovia **não existe** nos dados.

### A porta que nunca foi aberta

A `leapmotor-api` expõe quatro leituras de **histórico** que este conector nunca
chamou — verifiquei, zero ocorrências:

| método | o que é |
|---|---|
| `get_mileage_energy_detail` | **`/carownerservice/oversea/drivingRecord/v1/mileage/energy/detail`** |
| `get_consumption_last_week_breakdown` | consumo da semana |
| `get_consumption_weekly_rank` | ranking semanal |
| `get_charging_daily_detail` | recargas por dia |

`drivingRecord` é o **registro de condução do próprio carro**. Ele é read-only e,
o que importa, **não depende da nossa cadência**: é o carro reportando ao
fabricante o que rodou, inclusive o que a nossa amostragem nunca viu.

Isso também explica por que nenhuma viagem do site tem "Dado oficial": os campos
`official_trip_*` são raspados de escalares de dentro do payload de status
(`officialTripDistanceKm`, `tripMileage`…), e este carro não publica nenhum
deles.

### O que esta release faz — e o que ela deliberadamente NÃO faz

`POST /v1/vehicles/driving-record` chama os quatro métodos e devolve **só a forma
da resposta**: quais campos existem, de que tipo, listas com quantos itens. Um
número vira o seu tipo e a sua ordem de grandeza; um texto vira o seu tamanho.
**Nenhum valor sai** — um diagnóstico que despeja o histórico do dono no log é
vazamento, não diagnóstico.

Ela sobrevive a método ausente e a método que levanta, porque saber **quais**
respondem é exatamente o objetivo.

**Ela não consome nada.** Nenhum campo novo de telemetria, nenhuma mudança em
viagem, nenhuma leitura automática. Isso é deliberado: a decisão do wakeUp na
1.12.70 quase virou código inerte por ter sido escrita **antes** de alguém olhar
o que a biblioteca oferecia. Primeiro se mede, depois se escreve o consumidor.

A rota passa pelas **mesmas travas** das outras leituras de conta: ela fala com a
Leapmotor, então não fura a fila nem compete com um comando do dono.

### O contrato

`test_driving_record_probe_1_12_72`, 5 verificações, todas exercitando o
comportamento com dublês:

- a sonda cobre as quatro leituras e sobrevive a uma ausente e a uma que levanta,
  reportando cada caso como tal;
- a forma preserva os **nomes** dos campos e **nenhum valor** — o teste passa um
  payload com quilometragem, energia, data e VIN e exige que os quatro sumam
  enquanto `mileage`, `energy`, `startTime` e `records` continuam lá;
- a profundidade é cortada em payload aninhado;
- a rota está dentro do bloco da trava de conta;
- **nada foi ligado no caminho automático** — o motor de telemetria não menciona
  o histórico, e a cadência continua idêntica.

### Como usar

Uma chamada, uma vez, com as credenciais da conta. O retorno diz quais das quatro
leituras existem para este carro e que campos elas trazem. **Só depois** disso
faz sentido decidir o que aproveitar — e aí sim escrever o consumidor.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- Nenhuma mudança na matriz de comandos, na cadência ou na janela de confirmação.
- `Dockerfile` intocado.
- `config.yaml` intocado: o CI o promove depois de a imagem ficar pública.
