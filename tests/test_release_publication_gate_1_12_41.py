import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "leaphub_gateway"

# Piso histórico: a última versão anunciada antes de a publicação em duas fases
# existir. Não é "a versão anterior a esta release" — é uma alternativa fixa.
# 1.12.75 — mantido por referência histórica; a checagem que o usava virou
# comparação de ordem (ver abaixo).
LEGACY_PUBLISHED = "1.12.48"


def test_release_target_is_runtime_version_and_config_may_be_staged():
    """O alvo é o que o código anuncia; o config anda atrás, nunca à frente.

    1.12.70 — este contrato carimbava `assert target == "1.12.69"` e, por
    construção, reprovava toda release seguinte até alguém lembrar de editá-lo.
    Nona ocorrência do mesmo vício no projeto. O que ele existe para comprar não
    é um número: é que o `RELEASE_TARGET` tenha forma de versão, que os módulos
    anunciem exatamente ele, e que o `config.yaml` só possa estar atrás — nunca
    à frente, que é o estado em que o Home Assistant ofereceria uma imagem que
    ainda não existe no GHCR.
    """
    target = (APP / "RELEASE_TARGET").read_text(encoding="utf-8").strip()
    config = yaml.safe_load((APP / "config.yaml").read_text(encoding="utf-8"))

    assert re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", target), target
    # 1.12.75 — esta linha exigia que o config fosse EXATAMENTE o alvo ou uma
    # versão legada carimbada, e por isso reprovava toda release em que o config
    # ainda não tinha sido promovido — que é o estado normal da fase 1. A
    # garantia real (o config nunca à frente do alvo) está logo abaixo, e é ela
    # que protege o Home Assistant de receber uma imagem que não existe.
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:\.\d+)?", str(config["version"])), config["version"]

    def version_tuple(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in value.split("."))

    assert version_tuple(config["version"]) <= version_tuple(target), (
        "o config.yaml anuncia uma versão maior que o alvo; o Home Assistant "
        "ofereceria uma imagem que o GHCR ainda não tem"
    )

    # E o alvo é o que o runtime realmente diz ser. Sem isto, bumpar só o
    # RELEASE_TARGET publicaria uma imagem que se apresenta com outro número —
    # foi assim que cinco arquivos ficaram sem bump na 1.12.52.
    for name, constant in (
        ("connector.py", "CONNECTOR_VERSION"),
        ("connector_server.py", "VERSION"),
        ("gateway_manager.py", "VERSION"),
        ("ocpp_gateway.py", "GATEWAY_VERSION"),
        ("privacy.py", "PRIVACY_VERSION"),
        ("telemetry_engine.py", "ENGINE_VERSION"),
    ):
        source = (APP / name).read_text(encoding="utf-8")
        assert re.search(rf'^{constant} = "{re.escape(target)}"', source, flags=re.MULTILINE), (
            f"{name} não anuncia o alvo {target}"
        )

    # E as notas do alvo existem, nos dois lugares em que a recuperação manual
    # as procura.
    assert (APP / f"RELEASE-{target}.md").is_file()
    assert (ROOT / f"RELEASE-{target}.md").is_file()
    assert re.findall(
        r"^##\s+(.+)$", (APP / "CHANGELOG.md").read_text(encoding="utf-8"), flags=re.MULTILINE
    ) == [target]


def test_home_assistant_version_is_promoted_only_after_public_image_check():
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "RELEASE_TARGET" in workflow
    assert "Verify anonymous GHCR access before exposing update to Home Assistant" in workflow
    assert "Promote App metadata only after image is public" in workflow
    assert "continue-on-error: true" not in workflow
    assert workflow.index("Verify anonymous GHCR access") < workflow.index("Promote App metadata only")
    assert "contents: write" in workflow
    assert "[gateway-published]" in workflow
