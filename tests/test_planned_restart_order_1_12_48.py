from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANAGER = (ROOT / "leaphub_gateway" / "gateway_manager.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "leaphub_gateway" / "config.yaml").read_text(encoding="utf-8")
TARGET = (ROOT / "leaphub_gateway" / "RELEASE_TARGET").read_text(encoding="utf-8").strip()


def test_staged_release_metadata():
    # Publicação em duas fases: o `config.yaml` só anuncia o alvo depois que a
    # imagem está pública; até lá fica exatamente uma versão atrás. Derivado do
    # RELEASE_TARGET de propósito — carimbar o literal aqui obrigava a editar
    # este contrato a cada release, e era ele que reprovava sozinho na cópia
    # promovida da validação.
    major, minor, patch = (int(part) for part in TARGET.split("."))
    anterior = f"{major}.{minor}.{patch - 1}"
    assert any(f'version: "{v}"' in CONFIG for v in (TARGET, anterior)), (
        f"config.yaml precisa anunciar {TARGET} (promovido) ou {anterior} (aguardando)"
    )
    assert f'VERSION = "{TARGET}"' in MANAGER


def test_tunnel_starts_after_local_origin_gate():
    assert "def wait_for_local_origins" in MANAGER
    origin_start = MANAGER.index('if name != "tunnel":\n        service.start()')
    readiness = MANAGER.index("origin_readiness = wait_for_local_origins")
    tunnel_start = MANAGER.index('SERVICES["tunnel"].start()')
    assert origin_start < readiness < tunnel_start


def test_planned_shutdown_closes_tunnel_first():
    shutdown = MANAGER[MANAGER.index("def shutdown"):MANAGER.index("for signal_name")]
    assert '("tunnel", "ocpp_wallbox", "connector")' in shutdown
