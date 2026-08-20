## 1.12.121

- mantém a distribuição pré-compilada no GHCR oficial e a publicação em duas fases;
- corrige os comandos 301/370 de aquecimento e ventilação dos bancos no C10;
- substitui o envelope legado aceito sem efeito (`{"value":"posição,nível"}`)
  pelo contrato efetivo `{"position":"driver|copilot","level":"0..3"}`;
- recusa posições numéricas antigas para impedir ACK falso e novas tentativas
  físicas sem efeito;
- preserva clima, desembaçador, volante, retrovisores, cadência 1.12.120,
  dependências, banco de dados e todos os dados já coletados;
- `config.yaml` anuncia 1.12.120 até o CI validar e publicar a imagem 1.12.121.
