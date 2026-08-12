# Recuperação GitHub — Gateway 1.12.75

1. Envie somente os arquivos de `CHANGED-FILES-1.12.75.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.75`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.74` até a imagem nova estar
   pública. O commit da 1.12.75 não toca esse arquivo, então a promoção anterior
   fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`, a matriz de comandos, o schema do
add-on nem a escada de cadência. Ela conserta um defeito que eu introduzi na
1.12.74: o **orçamento de leituras** da janela de confirmação passou a encerrar
a espera antes do prazo.

Duas linhas de comportamento, em dois arquivos:

- `leaphub_gateway/telemetry_engine.py` — o piso de `command_max_polls` deixou
  de ser a constante `COMMAND_MAX_POLLS_FLOOR` e passou a ser **derivado**:
  quantas leituras cabem em `COMMAND_WINDOW_CEILING_SECONDS` (180s, o mesmo teto
  de `signal_presence`) com o menor degrau da escada, mais uma. Hoje dá 31.
  `COMMAND_MAX_POLLS_CEILING` subiu de 12 para 64 para acomodá-lo.
- `leaphub_gateway/gateway_manager.py` — o intervalo de normalização da opção
  acompanha o teto novo. O manager normaliza **antes** de o motor ver o valor;
  se os dois discordarem, o piso do motor nunca chega a valer.

**Não há custo de tráfego.** Quem marca o ritmo das leituras é a cadência e quem
limita a duração é `command_until`; o orçamento só truncava a espera mais cedo.

## Por que o número não pode voltar a ser escolhido à mão

Com a escada de 1.12.73 a 8ª leitura caía aos 382s, muito além dos 180s da
janela: o teto nunca disparava primeiro, e por isso ninguém notou que ele era o
critério de encerramento. A escada de 1.12.74 pôs a 8ª leitura aos 195s, e uma
única leitura extra bastou para o teto passar na frente do prazo. Derivar o piso
da janela remove a classe inteira do defeito.

`tests/test_command_budget_window_1_12_75.py` reprova a 1.12.74 com a aritmética
explícita e traz os dois casos de campo de 11/08/2026 (135s e 60s de janelas de
180s), além de três controles negativos.
