"""Wave 1 language-neutral configuration resolution conformance vector."""

from config import (
    ConfigLayer,
    FieldKind,
    FieldSpec,
    LayerPhase,
    MergeMode,
    SecretRef,
    resolve,
)

EXPECTED_CANONICAL = (
    '{"schema_version":"config.v1","values":{"endpoint":"https://api.example",'
    '"features":{"audit":true,"safe":false},"retries":5,"token":{"redacted":true,'
    '"secret_ref":{"logical_name":"worker-token","provider":"vault",'
    '"version_policy":"pinned:v3"}}}}'
)
EXPECTED_DIGEST = "sha256:7b4fbfa24ec3c61e427833bb256fb0be4232caba204d53cd74b433aea7a49b11"


def _resolution():
    specs = {
        "endpoint": FieldSpec(FieldKind.STRING, required=True),
        "features": FieldSpec(FieldKind.MAP, MergeMode.MAP_MERGE, required=True),
        "retries": FieldSpec(FieldKind.INTEGER, required=True),
        "token": FieldSpec(FieldKind.SECRET_REF, required=True, sensitive=True),
    }
    return resolve(
        "config.v1",
        specs,
        [
            ConfigLayer(
                "code-defaults",
                LayerPhase.DEFAULTS,
                {
                    "endpoint": "https://default.invalid",
                    "features": {"safe": True},
                    "retries": 2,
                    "token": SecretRef("vault", "worker-token", "pinned:v2"),
                },
            ),
            ConfigLayer(
                "base-recipe",
                LayerPhase.BASE,
                {
                    "endpoint": "https://api.example",
                    "features": {"audit": True},
                },
            ),
            ConfigLayer(
                "approved-overlay",
                LayerPhase.OVERLAY,
                {
                    "features": {"safe": False},
                },
            ),
            ConfigLayer("study-substitution", LayerPhase.SUBSTITUTION, {"retries": 5}),
            ConfigLayer(
                "authorized-override",
                LayerPhase.OVERRIDE,
                {
                    "token": SecretRef("vault", "worker-token", "pinned:v3"),
                },
            ),
        ],
    )


def test_configuration_resolution_vector() -> None:
    result = _resolution()
    assert result.canonical_json.decode("utf-8") == EXPECTED_CANONICAL
    assert result.digest == EXPECTED_DIGEST
    assert result.provenance == {
        "endpoint": "base-recipe",
        "features": "approved-overlay",
        "retries": "study-substitution",
        "token": "authorized-override",
    }


def test_configuration_resolution_rejects_unknown_and_raw_secret_values() -> None:
    secret_spec = {
        "token": FieldSpec(FieldKind.SECRET_REF, required=True, sensitive=True),
    }
    try:
        resolve(
            "config.v1",
            secret_spec,
            [ConfigLayer("code-defaults", LayerPhase.DEFAULTS, {"token": "plaintext"})],
        )
    except TypeError:
        pass
    else:
        raise AssertionError("raw secret material was accepted")

    try:
        resolve(
            "config.v1",
            secret_spec,
            [ConfigLayer("code-defaults", LayerPhase.DEFAULTS, {"undeclared": True})],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unknown field was accepted")
