## Presença e timeout 1.11.74

A janela interativa encerra ao fechar a última aba. Timeouts temporários preservam a sessão e usam repetição curta protegida, sem novo login imediato.

## Telemetria interativa 1.11.74

Enquanto uma aba autenticada do Leap Hub permanece visível, o site renova uma janela curta de presença. O Gateway reutiliza a sessão da conta, consulta em intervalo configurável (20 s por padrão) e encerra o perfil rápido automaticamente após a saída. Portas e vidros são compostos de forma independente.

## Proteção de sessão 1.11.71

- A telemetria só consulta a Leapmotor durante uma janela ativada pela presença do usuário no Leap Hub.
- A sessão autenticada é reutilizada; não existe mais um novo login em cada ciclo de coleta.
- Cada operação cria no máximo uma tentativa de login e falhas usam espera progressiva de 5 min até 6 h.
- Falha de autenticação pausa a assinatura até nova confirmação das credenciais.
- Reenvios com as mesmas credenciais não removem a proteção de autenticação ou cooldown.
- Limite de requisições ativa cooldown padrão de 6 horas.
- Intervalos seguros: 30 s dirigindo/carregando, 5 min estacionado e 15 min em repouso.
- Quando a janela de presença termina, a sessão é encerrada e nenhuma consulta à nuvem continua.

## Automação autônoma 1.11.69

O Gateway reconecta, reativa assinaturas e continua a telemetria sem ação do usuário.

# Leap Hub Home Assistant

Versão atual do Gateway: **1.11.74**.

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
