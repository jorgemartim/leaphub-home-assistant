# Leap Hub Gateway 1.12.10

- Adiciona testes offline da matriz completa de 21 comandos remotos.
- Verifica pares ligar/desligar, abrir/fechar, travar/destravar e iniciar/parar.
- Verifica que `climate_off` continua usando o método específico `ac_off`.
- Testa os limites de cooldown de login e de excesso de requisições sem acessar a nuvem.
- Testa remoção de token, senha e VIN das mensagens de log.
- Faz a validação do repositório executar automaticamente os testes de contrato.
- Não altera fila, telemetria, OCPP nem a execução física dos comandos da 1.12.09.
