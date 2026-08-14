# GitHub Recovery — Gateway 1.12.87

Base pública atual antes da correção:

`47deee4c052c79f070722df44d4f0cd67dc26705`

Base funcional restaurada:

`27b8129b26d71cacf0df5ceb2547eafc75803f4d`

Regras:
1. nenhum reset --hard;
2. nenhum force push;
3. histórico 1.12.85/1.12.86 é preservado;
4. runtime volta à 1.12.84;
5. somente versão muda para 1.12.87;
6. equivalência é verificada byte a byte;
7. config.yaml continua em 1.12.86 no commit funcional;
8. GitHub Actions promove somente após testes;
9. Site permanece 1.12.358.
