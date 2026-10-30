# Gateway 1.12.132 — diagnóstico seguro de falhas de recarga

Base publicada: 1.12.131. A consulta real encontrou LeapmotorApiError, mas a revisão anterior descartava código e motivo e retornava probe_failed. O HTTP 400 retornado pelo Gateway não identificava o HTTP original da nuvem.

O leitor agora mantém somente HTTP (100–599), código API inteiro limitado e tipos fixos da estrutura da resposta. As falhas são classificadas como transporte, sessão não aceita, acesso negado, indisponibilidade temporária, recusa da API ou formato incompatível. Respostas de erro não se tornam histórico vazio, mesmo que contenham data.list vazia. O log usa apenas motivo fechado e códigos, sem identificadores nem mensagem/corpo da nuvem.

São usados os métodos reais de transporte e parser da biblioteca 0.3.2 em testes com rede simulada. Não houve troca de dependência nem alteração de endpoint, datas, fuso ou assinatura. A leitura continua restrita ao Beta, uma tentativa, sem login/refresh/retry/wake-up, com as mesmas travas, autorização e prioridade dos comandos. O caminho de viagens foi preservado.

A revisão corrige a perda do diagnóstico; não estabelece a causa da recusa específica. O próximo ensaio real com o Site Beta 1.12.448 poderá mostrar o código original. Não se promete importar valores nem corrigir os kWh históricos sem evidência.

Distribuição pré-compilada em duas fases: config.yaml anuncia 1.12.131 até build, testes da imagem e acesso público ao GHCR serem confirmados pelo workflow oficial. Nenhuma instalação remota no Home Assistant ou consulta à conta real foi feita no desenvolvimento.
