## 1.12.68

Distribuição pré-compilada preservada, com publicação em duas fases.

### A tampa fechada deixa de ser desenhada duas vezes

Relato do proprietário sobre a 1.12.67: com o porta-malas **aberto** o desenho
ficou correto; com ele **fechado**, a tampa ainda sobrepunha o carro.

A causa é uma camada que eu acrescentei sem evidência. O pacote exposto na
página de administração tem `05-carpic_tailgate_close`, e eu deduzi dali que ela
deveria entrar quando o porta-malas está fechado. No pacote que o gateway baixa
da nuvem o **corpo já traz a tampa fechada**, então desenhá-la de novo a
sobrepõe. `leapmotor_api._build_layer_list()` nunca a acrescenta — e nisso a
biblioteca está certa.

`carpic_tailgate_close.png` sai da pilha. As duas correções de ordem que estavam
provadas continuam: `tailgate_open` antes do corpo, e `*_window_close` antes da
porta somente quando a porta está aberta.

### O contrato simétrico

A 1.12.66 quebrou por camada **omitida**; a 1.12.67, por camada **acrescentada**.
Havia contrato para o primeiro caso e não para o segundo.

`test_nenhuma_camada_extra_alem_do_capo` exige que a nossa pilha não contenha
nada que `_build_layer_list()` não desenharia, com uma única exceção declarada:
`carpic_hood_open`, que a biblioteca nunca pede e cujo efeito foi verificado
compondo as camadas reais. Junto com o contrato de ausência, os dois lados agora
estão fechados.

### Sem efeito colateral

- Nenhuma mudança em credenciais, OCPP, MQTT, schema ou dados existentes.
- Cadência e confirmação de comando intocadas.
- `Dockerfile` intocado.
