## 1.12.64

Distribuição pré-compilada preservada, com publicação em duas fases.

### O desenho do veículo acompanha o estado, sem precisar de comando

Relato do proprietário em 01/08/2026: *"a imagem não atualiza em tempo real,
tenho que enviar um comando do controle para ela poder atualizar"*.

A telemetria já estava certa. Medido no site com duas portas abertas e o
porta-malas fechado: `doors_open: 2`, `trunk_open: false`, selo "2 aberta(s)" e
os dois marcadores corretos sobre a foto — tudo sem nenhum comando enviado.
Quem ficava para trás era só o desenho.

A causa está em `serialize_vehicle()`: a leitura FAST adia a imagem oficial
**sempre**, e os bytes só saem com `force_visual_bytes`, que era exclusivo do
`sync`. Na prática, apenas um comando manual movia a imagem — exatamente o que
o proprietário descreveu.

Agora a **assinatura visual** decide. Quando ela muda — de
`unlocked--trunk-open` para `unlocked--front-left-open--rear-left-open`, por
exemplo — a composição anterior deixou de descrever o veículo, e a imagem deixa
de ser secundária: passa a ser a única coisa errada na tela.

A decisão virou uma função pura, `should_defer_official_image()`, com três
regras em ordem de precedência:

1. **Comando manual aguardando sempre adia.** É a garantia da 1.12.28: o pacote
   de imagem não pode segurar a conta na frente de um comando.
2. **Assinatura nova não adia**, e força os bytes — só metadados fariam o site
   manter o desenho antigo, que é o defeito.
3. Fora isso, o perfil FAST adia, como antes.

### Custo

Uma composição por **mudança** de estado, não por leitura.
`_official_render_cache_key()` já evitava recompor estado repetido, e
`_IMAGE_LAST_SIGNATURE` registra por veículo qual estado já teve os bytes
entregues — um carro não interfere no desenho de outro.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- A prioridade do comando manual sobre a imagem, introduzida na 1.12.28,
  continua valendo e tem teste próprio.
- `Dockerfile` intocado. Distribuição continua pré-compilada via GHCR, com
  promoção somente após validação pública da imagem.
