# Leap Hub Gateway 1.12.50 — confirmação FAST independente

O Gateway passa a iniciar a confirmação de telemetria no encerramento do próprio
comando remoto. A atualização não depende de o site consultar o diário primeiro,
reutiliza a sessão autenticada e não repete nenhuma ação física.

O `boost` posterior do site permanece como recuperação idempotente: quando o
`request_id`, comando e veículo são os mesmos, a janela é apenas mantida e a
contagem de amostras não é reiniciada.

Sem migration. `config.yaml` permanece na versão publicada até o workflow validar
a nova imagem GHCR.
