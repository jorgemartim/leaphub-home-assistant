# Gateway 1.12.127

Correção de confirmação e observabilidade do conforto do Leapmotor C10.

- `seat_heat` e `seat_ventilation` passam a usar a mesma cadência rápida de
  releitura já aplicada ao clima, volante e retrovisores;
- a cadência apenas consulta a telemetria e nunca repete o comando físico;
- os dumps técnicos de clima continuam disponíveis em nível `DEBUG`, mas não
  ocupam mais o log normal do add-on;
- nenhuma tabela, amostra, fila ou configuração existente é removida ou
  recalculada.
