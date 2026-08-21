## 1.12.123

- mantém a distribuição pré-compilada no GHCR oficial e a publicação em duas fases;
- corrige o OFF do desembaçador dianteiro para não restaurar aquecimento em
  32 °C com ventilador no nível 7;
- envia um único cmd 170 com `operate=off` e `wshld=0`, sem comando físico
  complementar e sem repetição;
- preserva confirmação FAST, filas, telemetria e todos os dados coletados;
- `config.yaml` anuncia 1.12.122 até o CI validar e publicar a imagem 1.12.123.
