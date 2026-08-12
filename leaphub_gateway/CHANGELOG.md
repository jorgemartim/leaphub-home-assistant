## 1.12.78

Distribuição pré-compilada preservada, com publicação em duas fases.

Ao concluir um comando, o Gateway avisa o site na hora, em vez de esperar
que o ciclo do cron venha buscar o resultado. Medido em campo em 12/08/2026:
carro 3s, worker 6,2s, tela 41-65s — o intervalo inteiro era espera pela
descoberta. O anúncio é melhor esforço e não segura o worker; um site sem a
rota continua sendo reconciliado pelo ciclo, como antes.

Ver RELEASE-1.12.78.md.
