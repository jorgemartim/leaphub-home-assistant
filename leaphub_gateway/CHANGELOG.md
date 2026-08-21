## 1.12.124

- mantém a distribuição pré-compilada no GHCR oficial e a publicação em duas fases;
- devolve ACK rápido para desembacador e bancos, sem esperar a consulta interna
  lenta da biblioteca Leapmotor;
- cada gesto continua emitindo exatamente um comando físico e nunca entra na
  matriz de repetição automática;
- a confirmação por telemetria permanece autoritativa e segue em segundo plano;
- preserva o OFF mínimo do desembaçador, filas, telemetria e todos os dados coletados;
- `config.yaml` anuncia 1.12.123 até o CI validar e publicar a imagem 1.12.124.
