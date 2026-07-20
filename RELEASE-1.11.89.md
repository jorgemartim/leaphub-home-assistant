# Leap Hub Gateway 1.11.89

- cria fila prioritária por conta para comandos manuais;
- impede novas leituras automáticas enquanto um comando aguarda;
- permite que a leitura já iniciada termine no próximo ponto seguro;
- aguarda até 180 segundos sem marcar falha prematura;
- não ocupa uma vaga global enquanto espera a conta;
- adiciona estados `waiting_account` e `waiting_slot`;
- registra diagnóstico seguro do ocupante e do tempo de espera;
- mantém sessão, credenciais, histórico e proteção contra duplicidade.
