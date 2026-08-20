# Leap Hub Gateway 1.12.117 - correcao do fechamento da cortina

Base publicada obrigatoria: `70e045d77682db800ef19b72c2b8111bcada989b` (Gateway 1.12.116).

Correcao minima: sunshade_close reutiliza o caminho de sunshade_position
preenchendo 0%, que o Gateway converte para o valor nativo "0".

Congelado: uma unica transmissao por intencao, nenhum retry fisico para cortina,
sunshade_open inalterado, posicao 0-100 -> 0-10 inalterada, janelas/cortina fora
de ACK_FIRST, fence mecanico 1.12.113, SAFE retry somente climate_on/off, e
demais controles/Trips/OCPP/SQLite/cadencias.

Publicacao em duas fases: RELEASE_TARGET 1.12.117, config.yaml 1.12.116 ate o
Actions/Linux validar, construir/testar GHCR e o bot promover a versao.
