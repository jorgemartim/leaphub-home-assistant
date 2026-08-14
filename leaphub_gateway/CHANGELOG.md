## 1.12.86

Corrige regressões de latência e confirmação observadas na 1.12.85.

- status one-shot recupera token de forma cooperativa, com no máximo uma releitura;
- confirmação expirada reconecta cedo sem login escondido;
- telemetria não pode manter a conta indefinidamente aguardando o lock interno da sessão;
- precheck do comando deixa de esperar a trava global para um SELECT somente-leitura em WAL;
- falha assíncrona é anunciada imediatamente ao Site para liberar os controles;
- ACK-first, payloads C10, supersessão e teto de duas transmissões permanecem.
