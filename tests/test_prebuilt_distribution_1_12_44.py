from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
config=yaml.safe_load((ROOT/'leaphub_gateway'/'config.yaml').read_text())
target=(ROOT/'leaphub_gateway'/'RELEASE_TARGET').read_text().strip()
ocpp=(ROOT/'leaphub_gateway'/'ocpp_gateway.py').read_text()
# 1.12.77 — derivado: o config nunca passa do RELEASE_TARGET (duas fases).
_t = lambda v: tuple(int(x) for x in str(v).strip().strip('"').split('.'))
assert _t(config['version']) <= _t(target)
assert target=='1.12.77'
assert 'CREATE TABLE IF NOT EXISTS queue_scheduler_state' in ocpp
assert 'persistent_round_robin' in ocpp
assert 'queue_scheduler_state' in ocpp
print({'ok':True,'version':target,'distribution':'prebuilt-staged','fairness':'persistent-round-robin'})
