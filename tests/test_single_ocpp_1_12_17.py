from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_RELEASE_TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
APP = ROOT / "leaphub_gateway"
manager = (APP / "gateway_manager.py").read_text(encoding="utf-8")
ocpp = (APP / "ocpp_gateway.py").read_text(encoding="utf-8")
config = (APP / "config.yaml").read_text(encoding="utf-8")
privacy = (APP / "privacy.py").read_text(encoding="utf-8")

# 1.12.76 — o par de versões literais aqui colapsou num deslize de release e
# reprovava com o config legitimamente atrás do alvo (fase 1 da publicação em
# duas fases). Derivado da fonte: o config nunca pode passar do RELEASE_TARGET.
def _config_nao_passa_do_alvo() -> bool:
    def _t(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in v.strip().strip('"').split("."))
    alvo = _t((APP / "RELEASE_TARGET").read_text(encoding="utf-8"))
    cfg = _t(next(
        l.split(":", 1)[1] for l in (APP / "config.yaml").read_text(encoding="utf-8").splitlines()
        if l.startswith("version:")
    ))
    return cfg <= alvo


checks = {
    "version": _config_nao_passa_do_alvo() and f'VERSION = "{_RELEASE_TARGET}"' in manager,
    "privacy_version": f'PRIVACY_VERSION = "{_RELEASE_TARGET}"' in privacy,
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
    raise SystemExit("single OCPP 1.12.24 failed:\n- " + "\n- ".join(failed))
print({"ok": True, "checks": len(checks), "version": _RELEASE_TARGET})
