## 1.12.83

Fila de envio desacoplada da confirmação: o próximo comando de estado pode sair
assim que a nuvem aceita a escrita, enquanto a telemetria confirma em segundo plano.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- ACK-first ampliado, de forma conservadora, para porta-malas, janelas e cortina;
- confirmações antigas da mesma família são marcadas `superseded` quando uma intenção oposta posterior é registrada;
- lock/unlock, clima AUTO/OFF e demais comandos rápidos da 1.12.82 permanecem inalterados;
- rede secundária de imagem oficial deixa de rodar dentro da trava de conta da telemetria contínua; cache local continua permitido;
- teto curto de rede automática da 1.12.82 permanece;
- nenhuma terceira transmissão, nenhum aumento de polling e nenhuma mudança de autenticação.
