## 1.12.98

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

Evolução mínima sobre a 1.12.97 homologada em campo.

- confirma `sunshade_position` pela telemetria FAST usando `sunshade_percent`, sem alterar a transmissão e sem retry físico;
- uma nova porcentagem supersede a espera da porcentagem anterior;
- publica allowlist RAW do histórico Official diário comprovado no C10, mantendo unidade/escala como `unverified`;
- preserva `sunshade_open/close`, ACK-first, clima, trunk, janelas, 5/5/8, imagem, HMAC e OCPP.
