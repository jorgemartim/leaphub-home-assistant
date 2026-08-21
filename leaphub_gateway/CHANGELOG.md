## 1.12.122

- mantém a distribuição pré-compilada no GHCR oficial e a publicação em duas fases;
- confirma fisicamente aquecimento e ventilação dos bancos dianteiros;
- usa os sinais C10 2100/2101/2118/2119 já presentes na leitura bruta quando
  a `leapmotor-api==0.3.2` não publica os campos tipados;
- mantém motorista e passageiro independentes e valida exatamente os níveis
  0, 1, 2 e 3 antes de concluir o comando;
- não repete comandos físicos durante a confirmação;
- preserva dependências, banco de dados, telemetria histórica e dados coletados;
- `config.yaml` anuncia 1.12.121 até o CI validar e publicar a imagem 1.12.122.
