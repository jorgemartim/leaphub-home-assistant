# Gateway 1.12.130 — configuração compreensível e diagnóstico fiel

O painel interno agora mostra a versão realmente instalada e inclui uma auditoria
somente dos parâmetros numéricos não secretos. Valores antigos que podem alongar
a confirmação aparecem com o valor atual, o recomendado e o motivo, sem exibir
chaves, tokens, identificadores, VIN ou coordenadas.

A aba Configuração ganha nomes e descrições para todos os campos avançados de
telemetria, OCPP e Tunnel. O add-on não sobrescreve escolhas existentes: a pessoa
continua no controle da configuração e pode comparar o valor salvo com o perfil
recomendado no painel.

Não há migration nem alteração no SQLite, nas filas, nas transações, nas
credenciais ou na telemetria preservada.
