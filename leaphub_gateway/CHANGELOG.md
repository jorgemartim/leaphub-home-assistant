## 1.12.95

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- mantém controles e telemetria fora do caminho da imagem;
- carrega o ZIP visual de forma lazy, decodificando apenas as camadas utilizadas;
- usa WebP lossless de baixa latência (`method=0`) e contrato visual 16;
- usa dois workers puramente locais para reduzir fila entre contas;
- registra tempos separados de pacote/render/base64/total;
- polling, timeouts, payloads e Site permanecem inalterados.
