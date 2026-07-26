## 1.12.34

- Recupera o pipeline pré-compilado conhecido como estável na 1.12.31 e remove a regressão de publicação observada depois dela.
- Mantém build somente `amd64`, sem matriz e sem manifesto multi-arquitetura intermediário.
- Faz validação estática antes do Docker e smoke test somente depois de a imagem existir com todas as dependências.
- A verificação anônima do GHCR volta a ser informativa: uma propagação lenta do registry não invalida uma imagem que já foi construída e publicada.
- Adiciona resumo do release no GitHub Actions com tag exata, digest e estado de acesso anônimo.
- Mantém instalação pré-compilada no Home Assistant e CHANGELOG exibindo somente a versão atual.
- Nenhuma alteração de banco, OCPP, Wallbox, MQTT ou protocolo de comandos nesta versão de recuperação.
