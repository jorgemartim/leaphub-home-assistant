# Leap Hub Gateway 1.11.99

## Desligamento da climatização por modo ativo

- O primeiro desligamento continua usando o comando padrão da biblioteca.
- Se uma leitura nova ainda mostrar a climatização ligada, a segunda e última entrega usa `ac_switch` com `operate=close` e preserva o perfil ativo: resfriamento, aquecimento ou ventilação genérica.
- Resfriamento e aquecimento são identificados por sinais redundantes da telemetria, sem registrar VIN, e-mail, PIN ou credenciais.
- Uma leitura nova continua obrigatória: se o veículo permanecer ligado, o resultado final permanece `not_applied`.
- Não existe terceira tentativa automática.
- O log registra apenas a estratégia segura utilizada.

Nenhuma alteração de configuração é necessária. A aplicação física depende do suporte do modelo/firmware e deve ser confirmada no Beta.
