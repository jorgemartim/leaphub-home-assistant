# Recuperação do repositório — Gateway 1.12.41

1. Restaure os arquivos do release 1.12.41.
2. Confirme `version: "1.12.41"` em `leaphub_gateway/config.yaml`.
3. Execute `.github/scripts/validate_repository.py`.
4. Não copie arquivos SQLite/runtime de outra instalação sobre o App em uso.
5. Reinicie o App e confirme a saúde do OCPP/Connector antes de prosseguir.
