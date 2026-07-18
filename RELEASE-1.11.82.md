# Leap Hub Gateway 1.11.82

## Comandos remotos mais confiáveis

- O comando real é enviado primeiro; a própria ação pode acordar o veículo.
- O Gateway só envia uma operação de despertar separada quando a nuvem informa claramente que o carro está dormindo ou offline.
- Após despertar, uma sessão nova é criada antes de uma única repetição segura do comando.
- A interface recebe as fases reais: fila, preparação, despertar, reconexão, execução e confirmação.
- A telemetria rápida é liberada em 3 a 5 segundos após o envio, reduzindo o atraso dos controles.
- Respostas ambíguas depois que a nuvem aceitou a ação nunca provocam reenvio automático.

## Ordem de atualização

1. Atualize o Gateway para **1.11.82**.
2. Reinicie o App.
3. Atualize o Leap Hub Beta para **1.12.76**.
4. Teste um único comando e acompanhe as fases no botão.
