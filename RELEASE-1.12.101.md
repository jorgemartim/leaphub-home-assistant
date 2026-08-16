# Leap Hub Gateway 1.12.101

## Objetivo

Diagnosticar por que o C10 tem quatro janelas abertas fisicamente enquanto o Leap Hub mostra apenas duas, sem adivinhar IDs de sinais brutos.

## Diagnostico seguro

Quando o snapshot muda, o Gateway grava `WINDOW_TELEMETRY_DIAG positions=... states=... raw_candidates=...`.
`raw_candidates` nao e o payload bruto: o coletor e limitado e remove caminhos sensiveis.

## Imagem

O pacote oficial ja contem `carpic_leftbehind_window_close.png`. Os testes garantem que a camada aparece com o traseiro esquerdo fechado e some quando ele esta aberto. Tambem garantem as quatro tags no contrato visual.

## Preservado

- config.yaml permanece 1.12.100 ate a CI promover 1.12.101;
- nenhuma mudanca em dispatch/retry;
- nenhuma mudanca na cortina;
- nenhuma mudanca no OCPP.


## REV2 — contrato de versão do teste

O teste criado na 1.12.100 comparava `gateway_version` com a string literal
`"1.12.100"`. Isso fazia qualquer versão posterior falhar mesmo quando o runtime
informava corretamente sua nova versão.

A asserção agora compara com `telemetry.ENGINE_VERSION`. O contrato continua
verificando que o resultado enviado ao site traz a versão real do Gateway, mas
deixa de congelar a suíte em uma versão antiga. Nenhum código funcional foi
alterado por esta correção.

## REV3 — CHANGELOG de alvo único

O contrato de distribuição exige que `leaphub_gateway/CHANGELOG.md` tenha apenas
o cabeçalho do `RELEASE_TARGET`. A REV3 remove o cabeçalho histórico 1.12.100 e
mantém somente `## 1.12.101`.

## REV5 — contratos de distribuição revisados em conjunto

O CHANGELOG mantém um único cabeçalho `## 1.12.101` e restaura a frase histórica
“A distribuição continua pré-compilada no GHCR oficial e mantém publicação em
duas fases.”, exigida por contrato legado.

Antes da suíte ampla, a instalação REV5 executa individualmente todos os sete
contratos `prebuilt_distribution` existentes no repositório e o gate de
publicação. Nenhuma mudança funcional adicional foi feita.
