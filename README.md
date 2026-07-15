# Leap Hub Home Assistant

Versão atual do Gateway: **1.11.67**.

<p align="center">
  <img src="./leaphub_gateway/logo.png" alt="Leap Hub Gateway" width="420">
</p>

Repositório oficial do **Leap Hub Gateway** para Home Assistant OS.

O App reúne em um único container:

- Connector Leapmotor;
- gateway OCPP Beta;
- gateway OCPP Produção;
- Cloudflare Tunnel;
- painel de diagnóstico protegido pelo Ingress do Home Assistant.

## Instalação rápida

[![Adicionar repositório ao Home Assistant](https://my.home-assistant.io/badges/supervisor_store.svg)](https://my.home-assistant.io/redirect/supervisor_store/?repository_url=https%3A%2F%2Fgithub.com%2Fjorgemartim%2Fleaphub-home-assistant)

Ou adicione manualmente este endereço na Loja de Apps:

```text
https://github.com/jorgemartim/leaphub-home-assistant
```

Depois instale **Leap Hub Gateway**.

## Instalação rápida e confiável

As imagens são compiladas no GitHub Actions e publicadas no GitHub Container Registry. O Home Assistant baixa a imagem pronta, sem compilar Python, Alpine, Cloudflared ou dependências no equipamento do usuário.

Arquiteturas disponíveis:

- `amd64` — notebooks, mini PCs e servidores x86-64;
- `aarch64` será adicionado depois da validação da versão `amd64`.

## Documentação

- [Instalação](./INSTALL.md)
- [Documentação do App](./leaphub_gateway/DOCS.md)
- [Migração dos Apps antigos](./leaphub_gateway/MIGRATION.md)
- [Publicação de novas versões](./PUBLISHING.md)
- [Segurança](./SECURITY.md)
- [Changelog](./leaphub_gateway/CHANGELOG.md)

## Endereços internos

| Serviço | Porta interna | Origem do Cloudflare Tunnel |
|---|---:|---|
| Connector Leapmotor | 8094 | `http://local-leaphub-gateway:8094` |
| OCPP Beta | 8092 | `http://local-leaphub-gateway:8092` |
| OCPP Produção | 8093 | `http://local-leaphub-gateway:8093` |
| Painel Ingress | 8099 | Não publicar |

## Aviso

Este projeto não é um produto oficial da Leapmotor, da Cloudflare ou do Home Assistant. Credenciais, chaves HMAC e tokens nunca devem ser enviados ao GitHub.

## Teste de imagens por veículo

Nas Configurações do Leap Hub, o administrador escolhe um ou mais veículos e solicita o pacote visual. O Gateway atualiza o pacote oficial, envia a composição e uma galeria sanitizada de camadas, sem VIN, token ou credenciais.
