# Hotfix 1.11.56.1

Corrige `ModuleNotFoundError: No module named 'telemetry_engine'` no Connector Leapmotor.

A imagem agora contém o motor de telemetria em dois locais:

- `/app/telemetry_engine.py`
- `site-packages/leaphub_telemetry_engine.py`

O workflow executa um teste com a imagem exata antes de publicá-la no GHCR.

O site permanece na versão 1.11.57; somente o Leap Hub Gateway precisa ser atualizado.
