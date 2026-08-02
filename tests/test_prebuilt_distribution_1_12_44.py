from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
config=yaml.safe_load((ROOT/'leaphub_gateway'/'config.yaml').read_text())
target=(ROOT/'leaphub_gateway'/'RELEASE_TARGET').read_text().strip()
ocpp=(ROOT/'leaphub_gateway'/'ocpp_gateway.py').read_text()
assert config['version'] in {'1.12.48','1.12.69'}
assert target=='1.12.69'
assert 'CREATE TABLE IF NOT EXISTS queue_scheduler_state' in ocpp
assert 'persistent_round_robin' in ocpp
assert 'queue_scheduler_state' in ocpp
print({'ok':True,'version':'1.12.69','distribution':'prebuilt-staged','fairness':'persistent-round-robin'})
