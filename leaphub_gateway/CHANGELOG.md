## 1.12.75

Distribuição pré-compilada preservada, com publicação em duas fases.

O orçamento de leituras da janela de confirmação voltou a ser teto de segurança.
A 1.12.74 adensou a escada e manteve as mesmas 8 leituras, e com isso o teto
passou a encerrar a espera antes do prazo — medido em campo aos 135s e aos 60s
de uma janela de 180s. O piso agora é derivado da janela e do menor degrau da
escada, e elevá-lo não cria requisição nenhuma: quem marca o ritmo é a cadência.

Ver RELEASE-1.12.75.md.
