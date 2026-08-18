## 1.12.111

A distribuição continua pré-compilada no GHCR oficial e mantém publicação em duas fases.

- corrige a contenção SQLite comprovada em campo na 1.12.110: manutencao chegou a 39-42 s, `/boost` devolveu 503 e a confirmacao acumulou mais de 32 s de atraso;
- manutencao passa a ser best-effort, com 180 s de folga apos restart, intervalo de 60 s e busy timeout local de 150 ms;
- limpeza de eventos antigos passa a descobrir IDs por SELECT e alterar no maximo 200 linhas por classe/passada, em vez de DELETE/UPDATE bulk ilimitado;
- qualquer janela de comando ou confirmacao pendente faz a manutencao ceder antes de escrever;
- falha/ocupacao da manutencao nao marca o scheduler inteiro como indisponivel;
- adiciona `sqlite_writer_lock` dedicado, aplicado centralmente pelo `_db`: SELECTs seguem livres em WAL e todo write interno passa pelo mesmo coordenador;
- preserva o `schedule_lock` e todos os guardrails da 1.12.110;
- nao altera payload fisico, matriz de comandos, janelas, cortina, defrost, SAFE retry, auth/cooldown, OCPP nem cadencia 5/5/8;
- mantem `config.yaml` em 1.12.110 ate a publicacao normal via CI/GHCR.
