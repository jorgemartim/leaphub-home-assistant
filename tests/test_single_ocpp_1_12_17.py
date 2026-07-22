from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"
manager = (APP / "gateway_manager.py").read_text(encoding="utf-8")
ocpp = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
config = (APP / "config.yaml").read_text(encoding="utf-8")
privacy = (APP / "privacy.py").read_text(encoding="utf-8")

checks = {
    "version": 'version: "1.12.18.2"' in config and 'VERSION = "1.12.18.2"' in manager,
    "privacy_version": 'PRIVACY_VERSION = "1.12.18.2"' in privacy,
    "single_selection": "def selected_ocpp_configuration()" in manager,
    "ambiguous_blocked": "mantenha somente Beta ou Produção ativo" in manager,
    "single_target_env": '"LEAPHUB_INTERNAL_URL": internal_url' in manager and '"LEAPHUB_ENVIRONMENT": environment' in manager,
    "direct_launch_unique": 'OCPP ambíguo: defina LEAPHUB_ENVIRONMENT' in ocpp and 'if len(candidates) > 1' in ocpp,
    "no_secret_mirroring": "ocpp_beta_secret = ocpp_production_secret" not in manager and "ocpp_production_secret = ocpp_beta_secret" not in manager,
    "safe_default_limit": manager.count('or 20') >= 3 and config.count('ocpp_beta_max_connections: 20') == 1 and config.count('ocpp_production_max_connections: 20') == 1,
    "trusted_proxy_only": "peer.is_loopback or peer.is_private" in ocpp,
    "restart_counter_reset": "time.monotonic() - self.process_started_monotonic >= 300" in manager,
    "log_rotation": "MAX_MANAGED_LOG_BYTES = 10 * 1024 * 1024" in manager and "rotate_managed_log" in manager,
    "target_diagnostic": '"active_environment": ENVIRONMENT_LABEL' in ocpp and '"target_count": len(API_TARGETS)' in ocpp,
    "status_30_seconds": 'LEAPHUB_OCPP_STATUS_INTERVAL' in manager and 'STATUS_REPORT_SECONDS' in ocpp,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("single OCPP 1.12.18.2 failed:\n- " + "\n- ".join(failed))
print({"ok": True, "checks": len(checks), "version": "1.12.18.2"})
