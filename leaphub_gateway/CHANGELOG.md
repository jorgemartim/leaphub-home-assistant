## 1.12.133

- Compatibilidade com BOM UTF-8 inicial no JSON de recargas, mantendo validação de HTTP, código, esquema e registros.
- Perfil de formato, MIME e tamanho limitado no log, sem corpo, campos desconhecidos, identificadores ou credenciais. HTML/JSONP/resposta vazia não viram recargas de zero kWh.
- Registra motivos fechados dos adiamentos do Gateway, além do diagnóstico de conteúdo da nuvem.
- Mesma biblioteca 0.3.2, endpoint, fuso, assinatura, uma única leitura e prioridade/travas; sem login, refresh, retry ou comandos nessa consulta.
- Compatível com o Site Beta 1.12.449. Distribuição pré-compilada no GHCR em duas fases; config.yaml só anuncia 133 após os testes da imagem e acesso público.
