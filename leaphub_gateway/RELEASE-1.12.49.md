# Leap Hub Gateway 1.12.49 — sessão preservada no upsert

- Um `upsert` idêntico com `credentials_verified=true` não encerra mais uma sessão saudável.
- A confirmação administrativa deixa de aguardar a trava de uma telemetria em voo.
- Sem sessão ativa, a verificação ainda limpa bloqueios antigos e prepara uma recuperação coordenada.
- Credenciais alteradas e assinaturas desativadas continuam encerrando a sessão correspondente.
- Nenhum comando físico, retry de comando, intervalo de telemetria, fila OCPP, banco ou vínculo foi alterado.
