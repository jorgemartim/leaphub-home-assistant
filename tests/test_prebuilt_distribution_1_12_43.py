from pathlib import Path
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))
target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
build = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
ocpp = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
manager = (APP / "gateway_manager.py").read_text(encoding="utf-8")

assert target == "1.12.44"
assert config["version"] in {"1.12.43", "1.12.44"}
assert config["image"] == "ghcr.io/jorgemartim/leaphub-gateway"
assert re.findall(r"^##\s+(.+)$", (APP / "CHANGELOG.md").read_text(encoding="utf-8"), re.M) == ["1.12.44"]
assert "CREATE TABLE IF NOT EXISTS queue_owners" in ocpp
assert "fairness_scope" in ocpp
assert "_due_event_owner_heads" in ocpp
assert "_due_command_result_owner_heads" in ocpp
assert "ocppQueueCard" in manager
assert "import gateway_manager" not in build
assert "timeout 60s docker run" in build
assert (APP / "RELEASE-1.12.44.md").is_file()
print({"ok": True, "version": "1.12.44", "distribution": "prebuilt-staged", "fairness": "owner_user"})
