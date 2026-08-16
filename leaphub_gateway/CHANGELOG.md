## 1.12.101

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- diagnóstico sanitizado das quatro janelas do C10, sem registrar payload bruto sensível;
- `WINDOW_TELEMETRY_DIAG` só é emitido quando o snapshot de janelas muda;
- candidatos de `status.raw` ficam limitados a sinais escalares relacionados a janela/vidro;
- VIN, conta, token, senha, credenciais, certificado, GPS/localização, endereço e identificadores de dispositivo são excluídos;
- a camada oficial `carpic_leftbehind_window_close.png` fica protegida por teste para o vidro traseiro esquerdo;
- o contrato visual continua aceitando as quatro tags de janela;
- o teste de confirmação usa `telemetry.ENGINE_VERSION` em vez de congelar a string 1.12.100;
- nenhum comando físico, retry, cortina, clima ou OCPP é alterado nesta versão.
