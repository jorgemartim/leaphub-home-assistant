# Leap Hub Gateway 1.12.08

- Publica temperatura individual dos pneus quando o veículo realmente fornece esse dado.
- Mantém `tire_data` somente com pressão para compatibilidade com versões anteriores.
- Adiciona `tire_temperature_data` separado, sem estimar ou inventar temperatura.
- Reconhece nomes de campos usados por variantes/modelos compatíveis e ignora valores fora de faixa.
- Preserva prioridade de comandos manuais, cooldown e contenção de requisições da 1.12.07.
