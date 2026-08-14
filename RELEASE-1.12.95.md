# Leap Hub Gateway 1.12.95 — imagem lossless rápida sem interferência

Base publicada obrigatória: **1.12.94**
(`b96097d2c05d68a6079729ce194309dd3405acc4`).

## Evidência de campo da 1.12.94

- controles permaneceram no caminho crítico em aproximadamente 0,6 s;
- `climate_off` preservou exatamente duas transmissões seguras;
- coleta de telemetria caiu para cerca de 0,9–4 s depois do cold start;
- o antigo `serialize_vehicle` de 40–44 s desapareceu;
- render visual ficou isolado da conta, porém ainda mediu aproximadamente 7–11 s;
- múltiplas contas podiam formar fila no único worker visual.

## Correção 1.12.95

- troca a carga ansiosa de todas as camadas do ZIP por pacote visual lazy;
- apenas camadas exigidas pelo estado atual são decodificadas para RGBA;
- mantém pixels lossless, mas usa WebP `method=0` para priorizar latência;
- reduz compressão do PNG intermediário, que não é entregue ao Site;
- eleva o contrato visual para 16 e invalida cache antigo;
- usa dois workers exclusivamente locais para reduzir fila entre contas;
- registra `pacote`, `render`, `base64`, `total`, cache hit e camadas decodificadas;
- worker visual continua sem cliente, token, credenciais, sessão ou rede.

## Congelado

Não muda:
- ACK-first;
- payload C10;
- `climate_off` máximo de duas transmissões;
- porta-malas/cortina sem retry físico;
- supersessão;
- uma única sessão Leapmotor;
- bounded reads de 4 s;
- cadência de confirmação e cadência interativa;
- timeouts;
- Site/PWA.
