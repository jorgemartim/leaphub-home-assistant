# Recuperação do GitHub — Gateway 1.12.34

O repositório público precisa receber **também a pasta `.github`**. Atualizar apenas `leaphub_gateway/` mantém os workflows antigos e pode continuar falhando antes do build.

Arquivos críticos desta recuperação:

- `.github/workflows/build.yml`
- `.github/workflows/validate.yml`
- `.github/scripts/validate_repository.py`
- `leaphub_gateway/config.yaml`
- `leaphub_gateway/CHANGELOG.md`
- código atual do Gateway e testes de contrato.

Após o upload, confirme no GitHub que `leaphub_gateway/config.yaml` contém `version: "1.12.34"` e que o workflow novo possui o job `Validate, build and publish amd64 image`.

Espere o workflow de build finalizar antes de usar **Atualizar** no Home Assistant.
