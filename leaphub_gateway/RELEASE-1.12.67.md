## 1.12.67

Distribuição pré-compilada preservada, com publicação em duas fases.

### Corrige a 1.12.66: o carro saía sem as laterais

Relato do proprietário minutos após instalar a 1.12.66, com a imagem: o desenho
saiu sem as portas, mostrando o interior.

A 1.12.66 montou a pilha de camadas a partir do modelo do pacote exposto na
página de administração (760×355), onde **não existem** camadas `*_close` de
porta — só o corpo e sobreposições do que abre. O pacote que o gateway baixa da
nuvem é **outro** (1125×525) e **tem** essas camadas: `carpic_leftfront_close`,
`carpic_leftbehind_close`, `carpic_rightfront_close`, `carpic_rightbehind_close`
e `carpic_hood_close`. Omiti-las apagou as laterais do veículo.

A diferença entre os dois pacotes chegou a ser registrada na análise e mesmo
assim o modelo errado foi usado. É o mesmo erro de sempre: mudança visual
empacotada sem ver o resultado no pacote real.

Agora a pilha volta a incluir toda camada que a biblioteca desenharia, e move
**apenas os dois pares provados errados**:

- `carpic_tailgate_open` passa para ANTES de `carpic_body` (prefixo 01 contra
  02) — sem isso a tampa é desenhada na frente do carro;
- `carpic_*_window_close` vai para antes da porta **somente quando a porta está
  aberta**; com a porta fechada continua depois, como sempre esteve.

### O contrato que faltava

`test_nenhuma_camada_da_biblioteca_pode_sumir` compara a nossa pilha com a de
`leapmotor_api._build_layer_list()` em oito estados e exige que nenhuma camada
desapareça. Ele reprova a 1.12.66. Junto vão um controle direto (carro fechado
desenha as quatro portas) e a garantia de que nenhuma porta aparece aberta e
fechada ao mesmo tempo.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- Cadência e confirmação de comando intocadas.
- `Dockerfile` intocado.
