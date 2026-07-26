# Recuperação do repositório — Gateway 1.12.39

O pacote completo contém o repositório do App e pode substituir a árvore 1.12.38.
O pacote incremental contém somente os arquivos alterados.

Após aplicar:

1. confirme `version: "1.12.39"` em `leaphub_gateway/config.yaml`;
2. execute os testes Python;
3. publique a imagem do App;
4. reinicie o Gateway;
5. valide travar, destravar e clima no Beta.

Não configure MQTT com valores inferidos. O transporte continua passivo até
broker, autenticação, tópicos e payloads serem homologados.
