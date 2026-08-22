# Gateway 1.12.129

- Substitui um polling HTTP de comandos por wallbox por uma busca agregada de
  até 200 identidades por lote.
- Com 500 wallboxes ociosas, reduz aproximadamente 500 consultas por ciclo para
  três, mantendo resposta rápida quando existe comando.
- Executa no máximo 16 wallboxes em paralelo e preserva a ordem de até três
  comandos por equipamento.
- Mantém fallback individual durante a janela em que o Gateway novo ainda fala
  com um Site anterior à 1.12.417; a ordem recomendada é instalar o Site antes.
- Nenhum dado, fila OCPP, transação ou telemetria é removido ou migrado.
