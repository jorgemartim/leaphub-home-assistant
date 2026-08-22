# Gateway 1.12.130

- O painel Ingress passa a exibir a versão real do processo, sem rótulo fixo.
- Um diagnóstico sanitizado compara somente cinco parâmetros numéricos de
  latência com o perfil recomendado; chaves, URLs e credenciais não entram na
  resposta.
- Todos os campos avançados de Telemetria, OCPP e Tunnel recebem nomes e
  explicações em português e inglês.
- O perfil recomendado reduz confirmações excessivamente longas sem alterar a
  segurança do despacho e sem reenviar comandos físicos.
- Nenhuma fila, banco SQLite, telemetria, transação OCPP ou credencial é
  removida ou migrada.
