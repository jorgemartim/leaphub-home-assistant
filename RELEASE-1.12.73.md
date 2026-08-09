## 1.12.73

Distribuição pré-compilada preservada, com publicação em duas fases.

Uma leitura que o site nunca vai aceitar deixa de ser reenviada para sempre.

### O que estava acontecendo

Medido em 09/08/2026, no registro deste Gateway:

```
06:04:33 WARNING Entrega de 1 evento(s) adiada: O site recusou parte do lote.
06:06:34 WARNING Entrega de 1 evento(s) adiada: O site recusou parte do lote.
...      a cada ~2 minutos, sempre "1 evento"
12:48:36 WARNING Entrega de 1 evento(s) adiada: O site recusou parte do lote.
```

Quase sete horas, **a mesma leitura**, cerca de **700 tentativas por dia**. Do
outro lado, o registro do site apontava sempre o mesmo motivo: *"O veículo da
telemetria ainda não foi confirmado nesta conta."*

Três coisas se somavam:

1. o site respondia apenas **"recusado"**, e o Gateway entendia **"adiado"**;
2. a espera entre tentativas tem teto de dois minutos — então a repetição nunca
   desacelerava;
3. a limpeza da fila só apagava o que **já tinha sido entregue**, então uma
   leitura recusada não envelhecia nunca.

### O que muda

**A recusa passa a ter duas naturezas.** Desde a versão 1.12.328 do site, a
resposta diz, para cada leitura, se vale a pena tentar de novo. Falha passageira
— banco de dados ocupado, conexão instável, site fora do ar — continua sendo
repetida exatamente como antes. Recusa definitiva sai da fila, com o motivo
guardado e escrito no registro:

```
Entrega de 1 evento(s) descartada em definitivo pelo site:
O veículo da telemetria ainda não foi confirmado nesta conta.
```

**E a fila passa a desistir sozinha.** Esta metade não depende do site: uma
leitura que não foi entregue dentro da janela de retenção é abandonada, na mesma
janela em que a leitura entregue já era descartada. Com isso, nenhuma tentativa
pode se repetir indefinidamente — nem contra um site antigo, nem por um motivo
que ninguém previu.

Junto vem a limpeza que faltava: leitura descartada também sai do disco quando
envelhece. Sem isso, o conserto apenas trocaria repetição sem fim por acúmulo
sem fim.

### O que NÃO muda

- **Nada é descartado por conta própria.** O Gateway só abandona uma leitura
  quando o site diz explicitamente que ela nunca será aceita, ou quando ela já
  passou da janela de retenção — a mesma que sempre valeu para as entregues.
- Uma marca que não seja exatamente essa é lida como "tente de novo". Um site
  que ainda não conhece a novidade se comporta como sempre se comportou.
- Cadência, comandos, matriz de recursos, `Dockerfile` e esquema do add-on
  seguem iguais. Não há migração, e voltar para a 1.12.72 continua funcionando
  com as mesmas tabelas.

### Para o dono

Se a mensagem que aparecer for *"o veículo ainda não foi confirmado nesta
conta"*, o Gateway está lendo um carro que o site não reconhece naquela conexão.
Confirmar esse veículo no site, ou tirá-lo da configuração do Gateway, resolve a
origem — o descarte apenas impede que a tentativa se repita para sempre enquanto
isso não acontece.
