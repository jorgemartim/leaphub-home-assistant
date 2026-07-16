# Gateway 1.11.69

- Reconexão e sincronização totalmente automáticas.
- Watchdog reativa assinaturas recuperáveis após reinício ou falha transitória.
- Falhas temporárias desconhecidas retornam HTTP 503 e entram no ciclo de retry, não HTTP 500.
- Fila, credenciais criptografadas e escolha Manual explícita permanecem preservadas.
