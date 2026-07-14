# Política de segurança

## Nunca publique

- token do Cloudflare Tunnel;
- chaves HMAC do Connector;
- chaves dos gateways OCPP;
- credenciais da conta Leapmotor;
- PIN do veículo;
- arquivos de diagnóstico com dados pessoais;
- chave privada de assinatura do Leap Hub.

Os valores padrão em `config.yaml` permanecem vazios. As credenciais são salvas apenas no armazenamento do App dentro do Home Assistant.

## Exposição de portas

A porta `8099` pertence ao painel Ingress e não deve ser publicada na internet.

As portas `8092`, `8093` e `8094` devem ser acessadas somente pela rede interna dos Apps ou pelo Cloudflare Tunnel configurado.

## Relato de vulnerabilidade

Não abra uma Issue pública contendo credenciais, tokens, dados de localização ou informações pessoais. Faça o relato por um canal privado do responsável pelo Leap Hub.

## Dependências

O workflow utiliza imagens pré-compiladas, downloads verificados por SHA-256 e ações oficiais fixadas em versões determinadas.
