# Recuperação GitHub — Gateway 1.12.71

1. Envie somente os arquivos de `CHANGED-FILES-1.12.71.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.71`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.70` até a imagem nova estar
   pública. O commit da 1.12.71 não toca esse arquivo, então a promoção
   anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`, nem a matriz de comandos, nem o
schema do add-on. Ela troca o mecanismo do tempo limite do despacho introduzido
na 1.12.70.

A mudança tem **duas metades e elas são inseparáveis**:

- `_create_persistent_session_locked` volta a criar o cliente com
  `self.request_timeout_seconds` puro;
- `execute_command` envolve `connector.handle_command` em
  `self._dispatch_timeout(session["client"])`.

Aplicar só a primeira devolve o problema que a 1.12.70 resolveu (o despacho volta
a ter 2,3 s de folga contra o limite). Aplicar só a segunda é inofensivo mas
inútil, porque o cliente já nasceria alongado.

O gerenciador restaura o valor **no `finally`**. Se essa restauração se perder
numa recuperação manual, o cliente fica alongado depois do primeiro comando e a
leitura de telemetria volta a segurar a trava da conta por mais tempo — que é
exatamente o custo que esta release existe para remover, e nada na tela acusa.

Nada nesta release depende de estado no disco: não há migração, e uma instalação
que volte para a 1.12.70 continua funcionando com as mesmas tabelas.
