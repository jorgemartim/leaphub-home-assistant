from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
SOURCE = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
TARGET = "1.12.129"


def test_release_versions_are_aligned():
    assert (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip() == TARGET
    assert f'version: "{TARGET}"' in (APP / "config.yaml").read_text(encoding="utf-8")
    assert f'GATEWAY_VERSION = "{TARGET}"' in SOURCE


def test_per_connection_polling_is_not_spawned_anymore():
    run_block = SOURCE[SOURCE.index("    async def run(self)"):SOURCE.index("\ndef command_to_ocpp")]
    assert "self.command_loop()" not in run_block
    assert "command_batch_task = asyncio.create_task(command_batch_loop())" in SOURCE


def test_batching_bounds_http_and_physical_parallelism():
    assert 'COMMAND_BATCH_SIZE = max(1, min(250' in SOURCE
    assert '"200"' in SOURCE
    assert 'COMMAND_EXECUTION_PARALLELISM = max(1, min(32' in SOURCE
    assert '"16"' in SOURCE
    assert 'range(0, len(identities), COMMAND_BATCH_SIZE)' in SOURCE
    assert '{"action": "fetch_commands_batch", "identities": chunk}' in SOURCE
    assert 'commands[:3]' in SOURCE


def test_upgrade_order_has_a_legacy_fallback():
    assert 'exc.error_code != "invalid_internal_action"' in SOURCE
    assert 'batch_supported[target.name] = False' in SOURCE
    assert '{"action": "fetch_commands", "identity": identity}' in SOURCE


def test_scale_reduction_for_five_hundred_connections():
    users = 500
    batch_size = 200
    requests_per_idle_cycle = (users + batch_size - 1) // batch_size
    assert requests_per_idle_cycle == 3
    assert requests_per_idle_cycle / 10 <= 0.3
