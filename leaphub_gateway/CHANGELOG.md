# Changelog

## 1.11.63

- Usa o pacote oficial de imagens da API para compor localmente modelo, cor, portas, vidros, porta-malas e carga.
- Envia somente WebP final, hash e metadados seguros; não envia ZIP, chave do pacote, VIN ou credenciais.
- Corrige falso carregamento cruzando conector rápido/lento, estado plugado, potência e movimento/regeneração.
- Atualiza o contrato visual para a versão 7.

## 1.11.62

- Publica o contrato visual versão 6 com estado explícito `true`, `false` ou desconhecido por componente.
- Lista componentes conhecidos, desconhecidos e ativos sem interpretar ausência como fechado.
- Permite ao Leap Hub usar o contrato como fallback quando a estrutura detalhada do sensor vier incompleta.
- Inclui o contrato na fingerprint sem adicionar VIN, localização, credenciais ou identificadores da conta.
- Preserva fila ordenada, deduplicação semântica e heartbeats.
- Atualiza a versão do mapeamento para 1.11.62.

## 1.11.61

- Publica o estado visual versão 5 com pistas seguras de resolução do modelo e da cor.
- Informa a origem dos campos usados e se a imagem HTTPS reportada pela nuvem estava disponível.
- Adiciona avisos de identidade e lista dos grupos de sensores com cobertura incompleta.
- Mantém VIN, credenciais, localização e identificadores da conta fora do diagnóstico visual.
- Preserva fila ordenada, deduplicação semântica e heartbeats da versão anterior.
- Atualiza a versão do mapeamento para 1.11.61.

## 1.11.60

- Publica o estado visual versão 4 com diagnóstico de cobertura dos sensores.
- Separa a fingerprint do estado da fingerprint da amostra, evitando atualizações visuais desnecessárias.
- Ordena eventos por veículo e impede que uma leitura nova ultrapasse outra pendente.
- Suprime leituras semanticamente idênticas e mantém heartbeats seguros conforme o estado do carro.
- Adiciona sequência, tipo do evento e indicador de alteração real ao payload entregue.
- Mantém a última leitura no site quando o Home Assistant fica temporariamente indisponível, sem inventar dados.
- Atualiza a versão do mapeamento para 1.11.60.

## 1.11.59

- Atualiza a representação do veículo em tempo real sem recarregar a página inteira.
- Publica o estado visual versão 3 com identidade do modelo, cor, horário e fingerprint determinístico.
- Adiciona climatização, pré-aquecimento da bateria, carga concluída e retrovisores recolhidos aos componentes visuais.
- Mantém o payload sem VIN, credenciais ou identificadores de conta dentro da assinatura visual.
- Atualiza a versão do mapeamento para 1.11.59.

## 1.11.58

- Gera uma assinatura visual determinística para cada combinação de estado do veículo.
- Informa quais sensores de portas, vidros, teto, luzes e segurança realmente responderam.
- Diferencia estado fechado de estado não informado, evitando alertas falsos na interface.
- Prepara imagens completas e camadas transparentes por modelo, cor e componente.
- Atualiza a versão do mapeamento para 1.11.58.

## 1.11.57

- Envia `outColor` para o Leap Hub e preserva aliases de cor encontrados no retorno bruto.
- Amplia o estado visual com portas, vidros e percentuais individuais, teto solar, cortina, luzes, espelhos, sentinela e segurança.
- Envia climatização avançada, bancos, volante aquecido, conectividade, plano de carga, tipo de conector, tempo restante e estado dos pneus.
- Mantém compatibilidade com leituras antigas e com campos ausentes por modelo ou permissão.
- Atualiza a versão do mapeamento para 1.11.57.

## 1.11.56.1

- Corrige a inclusão e a importação do motor de telemetria na imagem publicada.
- Instala o módulo também em site-packages com nome interno exclusivo.
- Adiciona teste de runtime da imagem exata antes da publicação no GHCR.
- Mantém configurações, fila persistente, OCPP e Tunnel sem alteração.

## 1.11.56.1

- Corrige `ModuleNotFoundError: No module named leaphub_connector/connector`.
- Instala o Connector em `site-packages` com nome interno exclusivo.
- Adiciona autoteste obrigatório de importação na compilação Docker.
- Adiciona validação de presença e tamanho do arquivo `connector.py`.
- Registra no log o caminho do módulo carregado antes de iniciar os serviços.

## 1.11.54.2

- Dockerfile reorganizado para preservar o cache das camadas pesadas em compilações locais.
- Limites de conexão e tempo no download do Cloudflared.
- Correção da biblioteca compartilhada do Python.

## 1.11.54.1

- Migração para a imagem oficial `base-python` do Home Assistant.
- Correção do erro `libpython3.12.so.1.0`.

## 1.11.54

- App único para Connector, OCPP Beta, OCPP Produção e Cloudflare Tunnel.
- Painel Ingress responsivo com saúde, PID, reinícios, testes e logs recentes.
- Supervisão individual dos processos.
- Token do Tunnel fora da linha de comando.
- Migração reversível.
- Ícone, logotipo, traduções, documentação e política AppArmor.
