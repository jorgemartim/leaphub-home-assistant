# Leap Hub Gateway 1.11.85

Hotfix de estabilidade do Connector, telemetria contínua, imagem oficial e comandos remotos.

## Correções

- respostas canceladas pelo Cloudflare não geram mais HTTP 500 falso;
- status de comando responde pelo cache mesmo durante gravações SQLite;
- anti-replay não segura cada request por até três segundos;
- healthcheck não aguarda o relatório completo de telemetria;
- Cloudflare Tunnel usa HTTP/2 por padrão, com opção `auto` ou `quic`;
- nenhuma credencial, certificado ou base de telemetria é removida.
