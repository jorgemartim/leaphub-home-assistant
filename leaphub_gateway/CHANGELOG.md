## 1.12.87

Restaura o runtime conhecido e testado da Gateway 1.12.84 após regressões introduzidas nas tentativas 1.12.85 e 1.12.86.

A distribuição permanece pré-compilada no GHCR oficial e conserva a publicação em duas fases.

- os seis arquivos principais de runtime voltam byte a byte ao comportamento da 1.12.84, exceto pelo marcador de versão 1.12.87;
- removidas as alterações experimentais de one-shot/status recovery introduzidas depois da 1.12.84;
- ACK-first permanece;
- supersessão permanece;
- anúncio imediato Gateway para Site permanece;
- payloads Leapmotor C10 permanecem;
- climate_off continua limitado a no máximo duas transmissões idênticas;
- nenhuma terceira transmissão;
- nenhum wake artificial;
- nenhuma segunda sessão Leapmotor concorrente;
- nenhum aumento de polling;
- Site não faz parte desta release e permanece em 1.12.358;
- config.yaml permanece 1.12.86 no commit funcional e somente o GitHub Actions poderá promovê-lo para 1.12.87.
