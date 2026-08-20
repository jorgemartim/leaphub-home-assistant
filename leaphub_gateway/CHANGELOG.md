## 1.12.119

A distribuição continua pré-compilada no GHCR oficial e mantém a publicação em duas fases.

- corrige os payloads do aquecimento do volante e dos retrovisores no C10;
- volante ON/OFF usa agora `level=2`/`level=1`, conforme captura do aplicativo
  internacional, em vez do envelope legado `value=on`/`value=off`;
- retrovisores ON/OFF usa agora `value=2`/`value=1` pelo mesmo contrato verificado;
- os quatro comandos continuam com exatamente uma transmissão e sem retry;
- ACK da nuvem continua sem ser convertido em sucesso físico: a confirmação segue
  dependente da telemetria e da homologação no carro;
- clima, desembaçador dianteiro, janelas, cortina, Trips, OCPP, banco e cadências
  permanecem inalterados;
- nenhuma migration, exclusão ou recálculo de dado coletado é executado;
- `config.yaml` permanece em `1.12.118` até o CI construir, testar, executar o
  smoke test e confirmar acesso anônimo à imagem GHCR `1.12.119`.
