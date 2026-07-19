# Leap Hub Gateway 1.11.87

- reutiliza a sessão autenticada da telemetria durante comandos remotos;
- não encerra mais uma sessão válida antes da operação manual;
- usa a última lista válida de veículos para evitar nova validação desnecessária;
- mantém trava exclusiva por conta durante comando e telemetria;
- restaura o PIN temporário da sessão depois da ação;
- diferencia aceite do Gateway de envio efetivo à nuvem;
- preserva sessão em falhas transitórias e só invalida em erro real de autenticação;
- aplica novas tentativas curtas ao banco persistente de nonces durante reinícios sobrepostos.
