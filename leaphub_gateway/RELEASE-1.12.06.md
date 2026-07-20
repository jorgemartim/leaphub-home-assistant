# Leap Hub Gateway 1.12.06

- Corrige a falha de inicialização `value must be at least 10.0` após atualizar da 1.12.04.
- Aceita temporariamente os valores antigos salvos pelo Home Assistant, sem exigir edição manual da configuração.
- Converte internamente o intervalo antigo de 3 segundos para o mínimo seguro de 10 segundos.
- Converte internamente até 12 verificações antigas para no máximo 4 verificações.
- Mantém o controle de requisições, backoff e proteção contra limite da nuvem da 1.12.05.
