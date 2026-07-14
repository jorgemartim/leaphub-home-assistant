# Leap Hub Gateway 1.11.56.1

## Visão geral

O Leap Hub Gateway executa quatro serviços supervisionados dentro de um único App:

- Connector Leapmotor;
- OCPP Beta;
- OCPP Produção;
- Cloudflare Tunnel.

O painel de diagnóstico é aberto pelo Ingress autenticado do Home Assistant.

## Serviços internos

| Serviço | Porta | Origem no Cloudflare Tunnel |
|---|---:|---|
| Connector Leapmotor | 8094 | `http://127.0.0.1:8094` |
| OCPP Beta | 8092 | `http://127.0.0.1:8092` |
| OCPP Produção | 8093 | `http://127.0.0.1:8093` |
| Painel Ingress | 8099 | Não publicar |

## Configuração

### Connector

- **Ativar Connector Leapmotor:** inicia o serviço na porta 8094.
- **Chave do Connector Beta:** mesma chave HMAC configurada no Leap Hub Beta.
- **Chave do Connector Produção:** chave separada para Produção.
- **Consultas simultâneas:** limite de operações paralelas contra a nuvem Leapmotor.

### OCPP

- **OCPP Beta:** usa por padrão `https://leaphub.com.br/beta/leap/api/internal/ocpp`.
- **OCPP Produção:** usa por padrão `https://leaphub.com.br/leap/api/internal/ocpp`.
- Cada ambiente possui chave e limite de conexões próprios.

### Cloudflare Tunnel

- O token é mantido no armazenamento privado do App.
- O Tunnel deve ser ativado somente depois de as origens públicas apontarem para `local-leaphub-gateway`.
- O token não é colocado na linha de comando do processo.

## Primeira inicialização

Mantenha inicialmente:

```yaml
tunnel_enabled: false
ocpp_production_enabled: false
```

Inicie o App e confirme no painel:

```text
Connector Leapmotor  → em execução
OCPP Beta            → em execução
OCPP Produção        → desativado
Cloudflare Tunnel    → desativado
```

## Migração das rotas

No painel do Cloudflare Tunnel, altere apenas as origens internas:

```text
connector.leaphub.com.br
→ http://127.0.0.1:8094

ocpp-beta.leaphub.com.br
→ http://127.0.0.1:8092
```

Depois abra:

```text
https://connector.leaphub.com.br/health
https://ocpp-beta.leaphub.com.br/health
```

O retorno público esperado é:

```json
{"ok":true}
```

Quando os dois testes estiverem corretos, ative `tunnel_enabled`, reinicie o Gateway e pare os Apps antigos.

## Diagnóstico

O painel mostra:

- estado de cada serviço;
- PID e reinícios;
- última verificação de saúde;
- logs recentes separados;
- testes manuais;
- versão instalada.

As credenciais não são exibidas no painel nem nos endpoints públicos.

## Persistência

Os dados do App ficam em `/data`, incluindo configurações fornecidas pelo Supervisor, arquivos de execução e logs. Eles sobrevivem a reinícios e atualizações normais do App.

## Atualização

As imagens são pré-compiladas no GitHub. Ao atualizar, o Home Assistant apenas baixa a nova imagem e reinicia o App. Não é necessário Samba nem compilação local.

## Solução de problemas

### Erro 502 no Cloudflare

Confirme:

1. o Gateway está iniciado;
2. Connector e OCPP estão verdes no painel;
3. as origens usam `local-leaphub-gateway`;
4. as portas são 8094 e 8092;
5. o Tunnel está conectado.

### A imagem não baixa

Confirme se o pacote `ghcr.io/jorgemartim/leaphub-gateway` está público no GitHub Packages.

### O App não aparece na loja

Remova e adicione novamente o repositório, depois use **Verificar atualizações**.


## Telemetria contínua 1.11.56.1

O Gateway guarda credenciais e eventos criptografados em `/data/telemetry`, usa intervalos adaptativos e reenvia a fila quando o site volta. Eventos usam identificadores determinísticos para impedir duplicidade. Uma queda do Home Assistant inteiro cria uma lacuna real; o sistema não inventa rota, consumo ou posições.
