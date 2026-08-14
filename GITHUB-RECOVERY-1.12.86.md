# GitHub Recovery — Gateway 1.12.86 R2

Base obrigatória: `4e5552f90eb0bb5a849d37f9be6eaf543f196b3d`.

A tentativa R1 parou antes de stage/commit porque o contrato local procurava uma
grafia errada do payload C10. A R2 só restaura os arquivos da R1 se o conteúdo
local for exatamente o que o próprio patch R1 teria produzido; qualquer outra
alteração aborta sem descarte.

Depois da recuperação:
1. aplicar status one-shot com refresh cooperativo e uma única releitura;
2. limitar espera do lock de sessão da telemetria;
3. remover o lock global do SELECT somente-leitura do precheck do comando;
4. anunciar falha terminal do worker imediatamente ao Site;
5. validar o payload C10 real sem alterá-lo;
6. stage explícito somente de `CHANGED-FILES-1.12.86.txt`;
7. publicar sem force;
8. aguardar promoção automática antes de instalar.
