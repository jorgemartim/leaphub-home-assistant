# Recuperação GitHub — Gateway 1.12.32

Use este pacote quando o repositório GitHub ainda estiver em uma versão antiga e não contiver os módulos atuais do Gateway.

1. envie o conteúdo do ZIP para a raiz de `jorgemartim/leaphub-home-assistant`;
2. confirme `leaphub_gateway/config.yaml` com `version: "1.12.32"` e `image: "ghcr.io/jorgemartim/leaphub-gateway"`;
3. faça commit/push;
4. aguarde **Build and publish Leap Hub Gateway**;
5. se o GHCR estiver privado na primeira publicação, altere uma única vez a visibilidade do pacote `leaphub-gateway` para Public e reexecute o workflow;
6. somente com o workflow verde atualize o App no Home Assistant.

O workflow verde significa que a imagem exata da 1.12.32 foi construída, testada e está acessível anonimamente para o Supervisor.
