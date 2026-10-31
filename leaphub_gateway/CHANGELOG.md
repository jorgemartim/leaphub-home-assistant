## 1.12.135

- Consulta explícita de recargas usa segundos Unix e paginação textual, com assinatura dos mesmos campos enviados no corpo.
- Reconhece envelopes result/code zero consistentes com data.list válida e períodos chargeEarliestTs/chargeLatestTs; FAST/SLOW e códigos antigos mantidos.
- Respostas incompletas, conflitos de código e registros de outro veículo não viram dados válidos.
- Uma chamada autenticada, sem login/refresh/retry, importação ou alteração da energia local; sessão, limites e prioridade existentes preservados.
- Compatível com o Site Beta atual. Código 39 ainda exige confirmação real após instalar; config.yaml só anuncia 135 quando o workflow oficial completar a imagem pública e testada.
- Distribuição pré-compilada pelo workflow oficial; sem dependências instaladas pelo usuário no Home Assistant.
