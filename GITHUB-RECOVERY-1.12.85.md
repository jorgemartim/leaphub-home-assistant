# GitHub Recovery — Gateway 1.12.85

Base publicada obrigatória: `27b8129b26d71cacf0df5ceb2547eafc75803f4d`.

1. preservar `leaphub_gateway/config.yaml` anunciando 1.12.84 no commit funcional;
2. aplicar somente os arquivos listados em `CHANGED-FILES-1.12.85.txt`;
3. executar contrato 1.12.85, teste dinâmico do adaptador, `py_compile` e `git diff --check`;
4. preservar ACK-first, payloads C10, no máximo duas transmissões, supersessão e anúncio imediato ao Site;
5. publicar sem force push;
6. aguardar Actions construir/testar a imagem e criar o commit automático `[gateway-published]` antes de atualizar o Home Assistant;
7. considerar a correção homologada somente após teste físico com o carro em sleep.
