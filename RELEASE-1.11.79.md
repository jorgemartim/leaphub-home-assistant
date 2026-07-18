# Leap Hub Gateway 1.11.79

## Correção de comandos remotos

- Corrige a incompatibilidade entre o `remote_id` armazenado como `car_id` e o VIN exigido pela biblioteca de comandos.
- A sessão automática é encerrada antes do login manual, não depois, evitando conflito de token.
- O Gateway aceita um VIN protegido enviado pelo Leap Hub e também resolve instalações antigas pelo `car_id`.
- Erros 422 passam a registrar uma mensagem sanitizada no log para diagnóstico.

## Instalação

1. Atualize o App Leap Hub Gateway para **1.11.79**.
2. Reinicie o App e confirme a versão no painel.
3. Atualize o Leap Hub Beta para **1.12.73**.
4. Teste primeiro localizar o veículo e depois travar/destravar.
