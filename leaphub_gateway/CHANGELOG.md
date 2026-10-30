## 1.12.134

- Trata envelopes de erro com result/message: fallback de código estritamente numérico e limitado, somente quando code está ausente.
- Classifica mensagens conhecidas em categorias fechadas, sem texto externo no log ou resposta; avisos existentes de acesso, autenticação e indisponibilidade passam a reconhecer essas falhas.
- result 0 sem o contrato de sucesso não vira histórico vazio ou registro válido.
- Mesma API, biblioteca, assinatura, intervalo, travas e consulta única no Beta; nenhum recálculo de kWh ou escrita no histórico.
- Compatível com Site Beta 449, sem novo ZIP; distribuição pré-compilada com anúncio no Home Assistant somente após imagem pública e testada.
