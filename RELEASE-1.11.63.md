# Leap Hub Gateway 1.11.63

- Integra o pacote oficial de imagens do próprio veículo disponibilizado pela API Leapmotor.
- Compõe a imagem no Home Assistant, preservando modelo, cor e estados visuais.
- Não envia o pacote original nem credenciais para o site.
- Corrige falso carregamento e diferencia carga externa de regeneração.
- Mantém cache protegido e limita tamanho/quantidade dos arquivos do ZIP.
- Dá prioridade aos sensores físicos AC/DC quando flags genéricas de carregamento estiverem defasadas.
- Mantém metadados da imagem oficial em heartbeats deduplicados sem reenviar Base64.
- Reconhece o código interno T03 como família C10 somente no resolvedor visual.

