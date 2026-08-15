## 1.12.96

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- preserva ACK-first, payloads C10, retries físicos e isolamento de imagem/telemetria/controle;
- mantém a primeira confirmação praticamente imediata e aplica 5s → 5s → 8s somente à janela pós-despacho, preservando o degrau estrutural/interativo de 6s;
- não reduz a cadência interativa permanente nem cria polling de 1–2s;
- faz a sonda `drivingRecord` usar somente sessão persistente já pronta/autorizada, com descoberta SQLite bounded e ordem conta → vaga global de baixa prioridade → sessão;
- assina `begintime`/`endtime` em milissegundos junto com o VIN e envia exatamente uma chamada read-only;
- devolve somente shape redigido, mede apenas tamanho/latência seguros, limpa diagnóstico transitório e não promove `official_*` sem evidência real do C10;
- Site, HMAC, OCPP, render visual e Produção permanecem funcionalmente inalterados.
