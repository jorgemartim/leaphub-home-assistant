## 1.12.36

- Comandos passam a medir separadamente espera da conta, vaga do Connector, preparo/reuso de sessão, dispatch/result e verificação, permitindo identificar o gargalo real sem registrar credenciais ou VIN.
- Connection Orchestrator expõe o gargalo p95 dominante por ambiente para orientar otimizações futuras com dados reais.
- Event Transport coalesce wake-ups equivalentes por conta/veículo em uma janela de 1,5 s, reduzindo leituras redundantes sem aumentar polling e sem descartar o evento original.
- Confirmação rápida, prioridade manual, REST autenticado e fallback atuais foram preservados; MQTT Leapmotor segue desativado até homologação legítima.
- Distribuição pré-compilada via GHCR permanece inalterada em relação à 1.12.35.
