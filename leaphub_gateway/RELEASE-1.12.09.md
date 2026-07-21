# Leap Hub Gateway 1.12.09

- Adiciona contrato explícito Hub ↔ Gateway (`api_version=2`).
- Retorna versão do esquema de capacidades para evolução segura da API Leapmotor.
- Propaga `X-Request-ID` em respostas e logs sem expor credenciais, e-mail, PIN ou VIN.
- Recusa versões de protocolo incompatíveis com mensagem clara, evitando falhas silenciosas.
- Publica versão e contrato no `/health` e `/health/details`.
- Mantém fila, cooldown, telemetria de pneus e comportamento de comandos da 1.12.08.
