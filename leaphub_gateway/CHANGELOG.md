## 1.12.125

- mantém a distribuição pré-compilada no GHCR oficial e a publicação em duas fases;
- corrige o piso interno do cliente que transformava o teto de 4 s da
  telemetria automática em 12 s durante a autenticação;
- impede que uma primeira sessão fria retenha a conta por vários blocos longos
  antes de liberar um comando manual;
- preserva os timeouts maiores do despacho físico e a confirmação autoritativa
  por telemetria;
- não altera, migra, recalcula nem remove dados coletados.
