## 1.12.76

Distribuição pré-compilada preservada, com publicação em duas fases.

Uma confirmação por comando, também quando o boost traz `request_id`. A guarda da
1.12.74 só cobria o boost anônimo; com o id devolvido pelo site na 1.12.331, o
caso comum atravessava a guarda e ressuscitava a linha já confirmada. Medido em
campo: cinco dos seis comandos confirmavam duas vezes.

Ver RELEASE-1.12.76.md.
