# Leap Hub Gateway 1.12.18.2

## Recuperação de instalação

- remove a dependência da imagem GHCR ainda não publicada;
- força o Home Assistant a construir o Gateway pelo Dockerfile local;
- preserva todas as 44 opções, os 25 comandos, OCPP único, telemetria e filas;
- mantém o workflow de publicação para que uma versão futura volte à instalação rápida;
- nenhuma credencial é incluída no repositório.
