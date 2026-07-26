# Leap Hub Gateway 1.12.39

## Resultado

- A sessão autenticada por um comando manual permanece disponível para a
  confirmação FAST do mesmo veículo.
- O ciclo de confirmação não abre uma segunda autenticação imediatamente após
  o comando, reduzindo contenção e atraso de atualização.
- O reflexo incorporado à camada oficial da porta dianteira aberta é reconstruído
  a partir da base do veículo.

## Segurança

- Comandos continuam no REST autenticado.
- Um comando aceito ou possivelmente aceito nunca é repetido automaticamente.
- MQTT permanece passivo, sem broker, tópicos, credenciais ou publicação de ações.
- Nenhuma migration e nenhuma alteração destrutiva.

## Instalação

Atualize o App do Gateway 1.12.38 para 1.12.39, reinicie e confirme a versão no
painel. Depois instale o Leap Hub Beta 1.12.239.
