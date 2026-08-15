# Leap Hub Gateway 1.12.96 — confirmação rápida + sonda Official segura

Base obrigatória: `672d4dcca0f6928d21f8eb6141bf815fb9bdb5e8` (1.12.95 publicada).

## Escopo

1. Confirmação pós-comando: mantém o poll inicial imediato; um override exclusivo de command-mode usa 5s, 5s e 8s, depois retorna à cauda conservadora. O `command_cadence[0]=6s` e o teto interativo de 6s permanecem intactos para preservar o contrato 1.12.77.
2. `drivingRecord`: a rota existente reutiliza exclusivamente uma sessão persistente já pronta e autorizada para o veículo. A descoberta SQLite é read-only/bounded e a ordem operacional é conta → vaga global de baixa prioridade → sessão, igual à arquitetura da telemetria e do worker moderno de comando.
3. Janela oficial: `begintime` e `endtime` são obrigatórios em milissegundos, participam da assinatura e do corpo POST; há exatamente uma chamada read-only e nenhum retry/login/refresh próprio.
4. Escopo por veículo: além de pertencer ao cache da sessão, o veículo precisa pertencer a `vehicle_ids_json` da assinatura ativa. Em contas com várias assinaturas, a sonda procura uma sessão existente que esteja pronta e autorizada, em vez de escolher apenas a assinatura mais recente.
5. Privacidade: a sonda não retorna valores brutos, VIN, token, certificados ou credenciais; chaves dinâmicas/UUIDs/identificadores opacos são redigidos, o cache diagnóstico da biblioteca é limpo e `mapped_fields=[]` permanece até o C10 provar o schema real.
6. Observabilidade segura: duração, tamanho do corpo, tamanho do shape e tempos de espera das travas são métricas numéricas; nenhum conteúdo bruto entra nessas métricas.

## Congelado

- ACK-first e comandos físicos C10;
- `climate_off` / `operate=off` e teto de duas transmissões;
- sem retry físico de trunk/sunshade;
- uma sessão Leapmotor por conta;
- render visual 1.12.95 e dois workers locais;
- HMAC/rotas/API version existentes;
- OCPP;
- Site/PWA e Produção.

## Publicação

Commit funcional staged: `RELEASE_TARGET=1.12.96`, enquanto `config.yaml` permanece `1.12.95`. Somente o workflow oficial promove o metadata depois de build, smoke e acesso público ao GHCR.

## Validação de campo após instalar

Revalidar controles rápidos e medir confirmação de unlock/lock/trunk/clima. Depois executar a sonda read-only em uma janela conhecida do C10 e comparar apenas o schema/shape redigido antes de mapear qualquer campo como Official.
