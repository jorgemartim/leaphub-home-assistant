from pathlib import Path
import ast,re
ROOT=Path(__file__).resolve().parents[2]; APP=ROOT/"leaphub_gateway"
telemetry=(APP/"telemetry_engine.py").read_text(encoding="utf-8"); connector=(APP/"connector.py").read_text(encoding="utf-8"); server=(APP/"connector_server.py").read_text(encoding="utf-8"); target=(APP/"RELEASE_TARGET").read_text(encoding="utf-8").strip()
tree=ast.parse(telemetry); body=""
for node in ast.walk(tree):
    if isinstance(node,ast.FunctionDef) and node.name=="execute_command": body=ast.get_source_segment(telemetry,node) or ""; break
checks={
"target_191":target=="1.12.91","engine_191":'ENGINE_VERSION = "1.12.91"' in telemetry,"connector_191":'CONNECTOR_VERSION = "1.12.91"' in connector,
"no_global_acquire":"self.lock.acquire(" not in body,"no_global_with":"with self.lock" not in body,"metric_zero":"engine_lock_wait_ms = 0" in body,
"bounded_db":"self._db(timeout_seconds=COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS)" in body,"short_timeout":bool(re.search(r"^COMMAND_SUBSCRIPTION_READ_TIMEOUT_SECONDS = 0\.75$",telemetry,re.MULTILINE)),
"busy_temporary":"A fila local de telemetria não liberou a leitura de assinatura a tempo." in body,"session_lock_preserved":"with self._session_operation_lock(subscription_id):" in body,
"dispatch_timeout_preserved":'with self._dispatch_timeout(session["client"]):' in body,"bounded_reads_preserved":"TELEMETRY_NETWORK_BLOCK_CEILING_SECONDS = 4.0" in telemetry,
"no_second_client":"_TelemetryOneShotClient" not in telemetry,"temporary_server_mapping":"except connector.ConnectorTemporaryError as exc:" in server}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit("1.12.91 contract failed: "+", ".join(failed))
print({"ok":True,"checks":len(checks),"version":target})
