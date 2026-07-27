## 1.12.43

- Distribuição pré-compilada mantida via GHCR com promoção segura após validação pública da imagem.
- OCPP replay com justiça por usuário/conta e FIFO preservado por wallbox.
- Uma wallbox ou usuário com backlog não monopoliza mais o lote global de replay.
- Resultados de comandos OCPP usam o mesmo escalonamento justo.
- Diagnóstico do Gateway informa escopos ativos e maior backlog sem expor identificadores.
- Sem reset de SQLite, Charge ID, filas, credenciais ou configuração existente.
