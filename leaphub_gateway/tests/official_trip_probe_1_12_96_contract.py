from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SERVER = (ROOT / "leaphub_gateway" / "connector_server.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "leaphub_gateway" / "telemetry_engine.py").read_text(encoding="utf-8")
PROBE = (ROOT / "leaphub_gateway" / "official_trip_probe.py").read_text(encoding="utf-8")
CONNECTOR = (ROOT / "leaphub_gateway" / "connector.py").read_text(encoding="utf-8")


def test_library_raw_debug_logging_remains_suppressed():
    assert 'logging.getLogger("leapmotor_api").setLevel(logging.WARNING)' in CONNECTOR


def test_route_is_hmac_protected_early_and_has_safe_input_error():
    call = "TELEMETRY.execute_driving_record_probe(environment, payload)"
    verify = 'verify_signature("POST", self.path, body, self.headers)'
    pending = "pending_key = manual_operation_enter(environment, payload)"
    start = SERVER.index("    def do_POST(self) -> None:")
    end = SERVER.index("\n\nclass ConnectorHTTPServer", start)
    post = SERVER[start:end]
    assert post.count(call) == 1 and post.count(verify) == 1 and post.count(pending) == 1
    assert post.index(verify) < post.index(call) < post.index(pending)
    assert '"reason": "invalid_probe_input"' in post
    assert 'LOG.info("Sonda Official recusada por parâmetros ou escopo inválidos; conteúdo omitido.")' in post
    assert "result = connector.handle_driving_record(payload)" not in SERVER
    assert "driving-record não pode entrar no caminho manual prioritário" in post


def test_probe_is_bounded_read_only_and_reuses_only_authorized_existing_session():
    method = ENGINE.split("def execute_driving_record_probe(", 1)[1].split("def execute_account_operation(", 1)[0]
    for forbidden in ("create_client(", ".login(", "assert_account_cloud_allowed(", "with self.lock", "str(exc)", "connector.clean_message(str(exc))"):
        assert forbidden not in method
    assert "self._db(" not in method and "with self.lock" not in method
    assert 'as_uri() + "?mode=ro"' in method
    assert "timeout=0.15" in method and "timeout=0.10" in method
    assert "PRAGMA busy_timeout=150" in method and "PRAGMA busy_timeout=100" in method
    assert "PRAGMA query_only=ON" in method
    assert "vehicle_ids_json" in method and "remote_id not in authorized_ids" in method
    assert "current.get(\"client\") is not client" in method
    assert "_telemetry_request_timeout(client)" in method and '"session_reused": True' in method
    account = method.index("account_lock.acquire(timeout=0.10)")
    slot = method.index("operation_semaphore.acquire(timeout=0.10)")
    session = method.index("session_operation_lock.acquire(timeout=0.10)")
    assert account < slot < session
    assert method.index("session_operation_lock.release()") < method.index("operation_semaphore.release()") < method.index("account_lock.release()")


def test_early_schedule_is_command_only_and_interactive_contract_stays_at_six():
    assert "COMMAND_POST_DISPATCH_EARLY_CADENCE = (5, 5, 8)" in ENGINE
    assert "COMMAND_FIRST_POLL_CEILING_SECONDS = 6" in ENGINE
    assert "INTERACTIVE_SECONDS_CEILING = 6" in ENGINE
    assert "min(self.command_seconds, self.COMMAND_FIRST_POLL_CEILING_SECONDS)" in ENGINE
    assert "self.command_effective_cadence = (" in ENGINE
    assert "if effective_command_mode:" in ENGINE
    assert "interval = int(self.command_effective_cadence[cadence_index])" in ENGINE
    assert "poll_schedule_seconds" in ENGINE and "list(self.command_effective_cadence)" in ENGINE


def test_window_is_one_post_signed_redacted_measured_and_diagnostic_cache_cleared():
    assert '"begintime": str(begin_ms)' in PROBE and '"endtime": str(end_ms)' in PROBE and "body_params=body_params" in PROBE
    assert PROBE.count("client._post(") == 1
    assert "last_results.pop(PARSE_LABEL, None)" in PROBE
    assert 'return "<dynamic-key>"' in PROBE
    assert 'map_c10_daily_values' in PROBE and '"mapped_fields": mapped_fields' in PROBE
    assert '"raw_values_included": False' in PROBE and '"raw_response_included": False' in PROBE
    assert "_retry_on_token_expiry" not in PROBE
    assert '"response_body_bytes"' in PROBE and '"response_shape_nodes"' in PROBE
    assert "_UUID_KEY" in PROBE and "_LONG_HEX_KEY" in PROBE and "_OPAQUE_PREFIX" in PROBE
