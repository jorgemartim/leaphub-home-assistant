# GitHub Recovery - Gateway 1.12.101

Base publicada: `658a5ef07524ba34409c241052a5c1293d6f4606`. Worktree novo, testes antes do commit, push normal e sem force.


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
