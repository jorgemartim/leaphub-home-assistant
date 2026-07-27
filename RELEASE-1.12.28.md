# Leap Hub Gateway 1.12.28 — prioridade manual sem trabalho secundário

- Fecha a janela observada em produção em que um comando podia aguardar dezenas de segundos atrás de `leaphub-telemetry`.
- A telemetria continua concluindo a chamada de status já em voo; depois disso, se houver comando manual pendente, não inicia chamadas secundárias de imagem oficial.
- O pacote oficial de imagem também verifica a prioridade antes do download, reduzindo a ocupação máxima da conta sem cancelar requisições HTTP em voo.
- Não aumenta polling, não adiciona retry físico e não altera OCPP, Wallbox ou a matriz de comandos.
