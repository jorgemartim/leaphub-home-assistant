# Enviar ao GitHub

Repositório de destino:

```text
https://github.com/jorgemartim/leaphub-home-assistant
```

1. Extraia o ZIP.
2. Substitua no repositório os arquivos pelas versões extraídas, incluindo `.github`.
3. Faça commit e envie para `main`.
4. Abra a aba **Actions**.
5. Aguarde **Validate repository** e **Build and publish Leap Hub Gateway** ficarem verdes.
6. Confirme em **Packages → leaphub-gateway** que a tag da versão existe e está pública.
7. Só então recarregue a Loja de Apps no Home Assistant.

Para a versão rápida 1.12.18, a tag esperada é:

```text
ghcr.io/jorgemartim/leaphub-gateway:1.12.18
```
