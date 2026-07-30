## 1.12.63

Distribuição pré-compilada preservada, com publicação em duas fases.

### A cortina do teto lê o campo que é dela

No C10 e no B10 o vidro do teto é fixo: o único motor é o da cortina. A nuvem
publica a posição dela em `status.signal.1724`, que a `leapmotor_api` entrega como
`security.roof_opening` — e o connector consumia isso como teto solar.

Medido no carro do proprietário em 30/07/2026, nos dois sentidos: cortina aberta
→ 1724 = 100 e `roof_open_percent` = 100; cortina fechada → ambos 0. Enquanto
isso `sunshade_open` e `sunshade_percent` vinham nulos em todas as amostras.

- **Correção:** em C10/B10, quando não existe campo de cortina próprio,
  `security.roof_opening` alimenta a cortina e o teto fica nulo em vez de mentir.
- A figura do carro passa a acender o selo da cortina, e não o do teto solar.
- `sunshade_open` vira booleano, então o site consegue reconciliar o botão e o
  matcher de `sunshade_open`/`sunshade_close` finalmente tem o que ler — o
  comando já executava no carro; o que faltava era a leitura.
- A troca é condicionada ao modelo porque `vehicle.rightList` declara o direito
  160 (teto solar) mesmo nesses carros de vidro fixo: o direito não prova o
  mecanismo. Modelo com teto deslizante de verdade não é afetado.

**Nota de método:** o primeiro candidato foi o `signal.1256`, que subiu junto com
a abertura e não voltou ao fechar — reagia ao carro acordar. Um único experimento
teria trocado o mapeamento pela chave errada. O contrato afirma os dois sentidos
por isso.

### Sem alteração

- Cortina continua no direito 161 e teto solar no 160; os comandos não se
  misturam.
- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com
  promoção somente após validação pública da imagem.
