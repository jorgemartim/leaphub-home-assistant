## 1.12.120

A distribuição continua pré-compilada no GHCR oficial e mantém a publicação em duas fases.

- reduz a demora percebida na confirmação de clima e aquecimentos do C10;
- elimina, somente para conforto, o salto de releitura entre 18 s e 42 s que foi
  medido em campo após um `quick_heat`;
- mantém 5/5/8 s no início e passa a reler em 28/38/50 s quando o estado ainda
  não apareceu, sem reenviar o comando físico;
- trava, vidros, cortina, porta-malas, recarga, Trips e OCPP preservam a cadência
  anterior sem nenhuma leitura adicional;
- payloads verificados de volante e retrovisores, ACK-first, limites, prazo e
  confirmação por telemetria permanecem inalterados;
- nenhuma migration, exclusão, recálculo ou alteração de dado coletado é executada;
- `config.yaml` permanece em `1.12.119` até o CI construir, testar, executar o
  smoke test e confirmar acesso anônimo à imagem GHCR `1.12.120`.
