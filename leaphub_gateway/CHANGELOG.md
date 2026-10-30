## 1.12.131

- Consulta de histórico de recargas em uma página por solicitação, usando a sessão já aberta e a prioridade/travas do leitor Official existente.
- Novo endpoint HMAC `/v1/vehicles/charging-record`, com veículo autorizado, janela máxima de sete dias, fuso explícito e até cinco páginas de 25 registros.
- Retorna somente início/fim, AC/DC e energia da nuvem, sem VIN, coordenadas, credenciais ou resposta bruta.
- Nenhum login, refresh de token, retry automático, comando físico ou reescrita de transações/recargas nessa leitura.
- Distribuição pré-compilada no GHCR em duas fases: config.yaml continua em 1.12.130 até a imagem 1.12.131 passar pelo fluxo oficial de build, smoke test e acesso público.
