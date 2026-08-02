# Recuperação GitHub — Gateway 1.12.70

1. Envie somente os arquivos de `CHANGED-FILES-1.12.70.txt`.
2. Confirme `leaphub_gateway/RELEASE_TARGET` em `1.12.70`.
3. Preserve `leaphub_gateway/config.yaml` em `1.12.69` até a imagem nova estar
   pública. O commit da 1.12.70 não toca esse arquivo, então a promoção
   anterior fica preservada.
4. Aguarde testes, build, smoke test e verificação anônima do GHCR.
5. O workflow promove o `config.yaml` somente depois dessas verificações.

Esta release **não** altera o `Dockerfile`, nem a matriz de comandos, nem o
schema do add-on. Ela conserta o caminho de **falha** da janela de confirmação
de comando, o tempo limite do cliente que despacha os comandos, e o casamento
entre um boost e a espera que ele deve estender.

Três pontos que exigem atenção numa recuperação manual:

- **`_transient_backoff` ganhou um terceiro parâmetro** (`command_mode`) e o
  ponto de uso passa a informá-lo. Aplicar a mudança pela metade — a função nova
  com a chamada antiga — deixa a correção inerte, e nada na tela acusa.
- **O piso do tempo limite vive no código**, em
  `COMMAND_DISPATCH_TIMEOUT_FLOOR_SECONDS`, e é aplicado em
  `_create_persistent_session_locked`. Mudar só o padrão do `config.yaml` não
  chega a nenhuma instalação existente, porque as opções do add-on já estão
  gravadas.
- **`_match_pending_confirmation` e `_register_confirmation` andam juntos.**
  Adotar a espera anônima sem gravar nela o `request_id` faz a gêmea renascer na
  repetição seguinte do boost.

Nada nesta release depende de estado no disco: não há migração, e uma instalação
que volte para a 1.12.69 continua funcionando com as mesmas tabelas.
