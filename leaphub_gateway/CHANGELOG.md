## 1.12.132

- Preserva o código HTTP e código numérico da API em falhas do histórico de recargas, com motivos fechados e sem mensagem/corpo brutos.
- Distingue falha de conexão, sessão não aceita, acesso negado, indisponibilidade, recusa da nuvem e formato incompatível. Não transforma erro em recarga vazia ou energia zero.
- Testa o transporte e parser reais da biblioteca fixada, com respostas simuladas e sem login/comando físico.
- Mantém autorização, travas, timeout e uma única leitura de baixa prioridade restrita ao Beta; não muda endpoint, fuso, integração ou pagamentos.
- Distribuição pré-compilada no GHCR em duas fases: config.yaml continua 1.12.131 até a imagem 1.12.132 passar por build, testes e acesso público.
