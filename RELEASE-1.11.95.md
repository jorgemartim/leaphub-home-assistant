# Leap Hub Gateway 1.11.95

- Corrige pausas gerais excessivas que podiam manter a conta bloqueada por seis horas.
- Usa `Retry-After` quando a nuvem informa um prazo; sem prazo, reavalia em quinze minutos.
- Cooldowns antigos acima de uma hora são encurtados para uma verificação segura em cinco minutos.
- A reavaliação não apaga credenciais e não repete comandos remotos.
