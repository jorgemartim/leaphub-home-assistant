from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEXT=(ROOT/'leaphub_gateway'/'telemetry_engine.py').read_text(encoding='utf-8')
checks={
 'reason_column':'cooldown_reason TEXT NULL' in TEXT,
 'attempt_column':'last_auth_attempt_at REAL NOT NULL DEFAULT 0' in TEXT,
 'success_column':'last_auth_success_at REAL NOT NULL DEFAULT 0' in TEXT,
 'login_reason':"cooldown_reason='login'" in TEXT,
 'rate_reason':"cooldown_reason='rate_limit'" in TEXT,
 'interval_guard':'auth_attempt_min_interval_seconds = 150' in TEXT,
 'typed_response':'"cooldown_reason"' in TEXT,
 'automatic_backoff':'300 if failures >= 2' in TEXT,
}
failed=[k for k,v in checks.items() if not v]
if failed: raise SystemExit('auth recovery contract failed: '+', '.join(failed))
print({'ok':True,'checks':len(checks)})
