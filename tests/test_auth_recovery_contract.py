from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEXT=(ROOT/'leaphub_gateway'/'telemetry_engine.py').read_text(encoding='utf-8')
checks={
 'reason_column':'cooldown_reason TEXT NULL' in TEXT,
 'attempt_column':'last_auth_attempt_at REAL NOT NULL DEFAULT 0' in TEXT,
 'success_column':'last_auth_success_at REAL NOT NULL DEFAULT 0' in TEXT,
 'global_table':'CREATE TABLE IF NOT EXISTS account_auth_state' in TEXT,
 'progressive_backoff':'self.login_backoff_schedule = (300, 600, 1200, 1800)' in TEXT,
 'global_reservation':'def begin_account_auth' in TEXT and 'attempt_guard_until' in TEXT,
 'persistent_status':'def account_auth_status' in TEXT,
 'no_fixed_session_expiry':'self.session_max_age_seconds = 0' in TEXT,
 'refresh_before_login':'def _try_refresh_client_session' in TEXT,
 'upsert_hash':'config_hash' in TEXT and 'deduplicated' in TEXT,
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('auth recovery contract failed: '+', '.join(failed))
print({'ok':True,'checks':len(checks)})
