## Proteção de sessão 1.11.71

- A telemetria só consulta a Leapmotor durante uma janela ativada pela presença do usuário no Leap Hub.
- A sessão autenticada é reutilizada; não existe mais um novo login em cada ciclo de coleta.
- Cada operação cria no máximo uma tentativa de login e falhas usam espera progressiva de 5 min até 6 h.
- Falha de autenticação pausa a assinatura até nova confirmação das credenciais.
- Reenvios com as mesmas credenciais não removem a proteção de autenticação ou cooldown.
- Limite de requisições ativa cooldown padrão de 6 horas.
- Intervalos seguros: 30 s dirigindo/carregando, 5 min estacionado e 15 min em repouso.
- Quando a janela de presença termina, a sessão é encerrada e nenhuma consulta à nuvem continua.

## Automação autônoma 1.11.69

O Gateway reconecta, reativa assinaturas e continua a telemetria sem ação do usuário.

## Reconexão automática 1.11.69

O Gateway não depende de uma sessão permanente. Em cada ciclo ele autentica novamente usando as credenciais criptografadas. Quando a nuvem expira o token ou retorna uma falha temporária de verificação, o Gateway cria uma sessão nova, tenta até três vezes e agenda nova consulta sem desconectar a conta do Leap Hub. Somente uma recusa persistente e claramente relacionada à senha exige intervenção do usuário.

# Leap Hub Gateway

## Biblioteca visual 1.11.67

Cada composição oficial agora informa o estado principal, a assinatura, os componentes usados e um hash de consistência. O Leap Hub rejeita automaticamente uma imagem antiga quando ela não corresponde à telemetria atual e usa a biblioteca local como fallback. Os bytes continuam sendo reenviados somente quando a imagem realmente muda.



## Imagem oficial e validação de carregamento 1.11.63

O Gateway baixa de forma autenticada o pacote de imagens associado ao próprio veículo, monta localmente a imagem conforme portas, vidros, porta-malas e carga e envia somente a composição final ao Leap Hub. O pacote original, a chave do pacote, VIN e credenciais permanecem no Gateway. O estado de carregamento agora exige evidência de conector ou alimentação externa e não confunde regeneração com carga na tomada.

App unificado para Home Assistant OS que reúne Connector Leapmotor, OCPP Beta, OCPP Produção, Cloudflare Tunnel e painel de diagnóstico via Ingress.

A instalação pelo repositório oficial baixa uma imagem pronta do GitHub Container Registry. Não há compilação local no Home Assistant.

Leia a aba **Documentação** antes de migrar os Apps antigos. O Tunnel vem desativado por padrão para permitir a troca segura das rotas.


## Telemetria contínua 1.11.63

O Gateway mantém a fila criptografada, a sequência por veículo e a deduplicação da 1.11.60. A versão 1.11.63 publica o estado visual versão 7 com pistas seguras de resolução do modelo e da cor, informa se a imagem oficial da nuvem estava disponível e identifica grupos de sensores incompletos sem tratar ausência como estado fechado. Esses dados não incluem VIN, credenciais, localização ou identificadores da conta.
## Teste de imagens por veículo

Nas Configurações do Leap Hub, o administrador escolhe um ou mais veículos e solicita o pacote visual. O Gateway atualiza o pacote oficial, envia a composição e uma galeria sanitizada de camadas, sem VIN, token ou credenciais.
