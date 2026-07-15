# Leap Hub Gateway

## Consistência visual 1.11.64

Cada composição oficial agora informa o estado principal, a assinatura, os componentes usados e um hash de consistência. O Leap Hub rejeita automaticamente uma imagem antiga quando ela não corresponde à telemetria atual e usa a biblioteca local como fallback. Os bytes continuam sendo reenviados somente quando a imagem realmente muda.



## Imagem oficial e validação de carregamento 1.11.63

O Gateway baixa de forma autenticada o pacote de imagens associado ao próprio veículo, monta localmente a imagem conforme portas, vidros, porta-malas e carga e envia somente a composição final ao Leap Hub. O pacote original, a chave do pacote, VIN e credenciais permanecem no Gateway. O estado de carregamento agora exige evidência de conector ou alimentação externa e não confunde regeneração com carga na tomada.

App unificado para Home Assistant OS que reúne Connector Leapmotor, OCPP Beta, OCPP Produção, Cloudflare Tunnel e painel de diagnóstico via Ingress.

A instalação pelo repositório oficial baixa uma imagem pronta do GitHub Container Registry. Não há compilação local no Home Assistant.

Leia a aba **Documentação** antes de migrar os Apps antigos. O Tunnel vem desativado por padrão para permitir a troca segura das rotas.


## Telemetria contínua 1.11.63

O Gateway mantém a fila criptografada, a sequência por veículo e a deduplicação da 1.11.60. A versão 1.11.63 publica o estado visual versão 7 com pistas seguras de resolução do modelo e da cor, informa se a imagem oficial da nuvem estava disponível e identifica grupos de sensores incompletos sem tratar ausência como estado fechado. Esses dados não incluem VIN, credenciais, localização ou identificadores da conta.