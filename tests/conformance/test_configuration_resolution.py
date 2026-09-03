"""Wave 1 language-neutral configuration resolution conformance vector.

Every other suite in this directory is a ``unittest.TestCase`` with a
``unittest.main()`` entry point.  This module was written as bare pytest-style
functions with neither, and nothing in the estate runs pytest: the Bazel
``py_test`` executes it as a script, which imported the module, defined two
functions and exited zero, while ``unittest`` discovery found no tests at all.
The vector below therefore asserted nothing, in Bazel or anywhere else, from
the day it was written.  It is a TestCase now so that it runs.
"""

import unittest

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


class ConfigurationResolutionTest(unittest.TestCase):
    def test_the_vector_resolves_to_the_pinned_canonical_form(self) -> None:
        result = _resolution()
        self.assertEqual(result.canonical_json.decode("utf-8"), EXPECTED_CANONICAL)
        self.assertEqual(result.digest, EXPECTED_DIGEST)
        self.assertEqual(
            result.provenance,
            {
                "endpoint": "base-recipe",
                "features": "approved-overlay",
                "retries": "study-substitution",
                "token": "authorized-override",
            },
        )

    def test_raw_secret_material_is_rejected(self) -> None:
        """A secret may only ever arrive as a reference, never as a value."""

        with self.assertRaises(TypeError):
            resolve(
                "config.v1",
                {"token": FieldSpec(FieldKind.SECRET_REF, required=True, sensitive=True)},
                [ConfigLayer("code-defaults", LayerPhase.DEFAULTS, {"token": "plaintext"})],
            )

    def test_a_declared_merge_mode_is_actually_consulted(self) -> None:
        """The defect this vector was written to catch, stated directly.

        `resolve` assigned every field unconditionally, so `MergeMode` was dead
        configuration: declaring MAP_MERGE and declaring REPLACE produced the
        same answer.  Two fields differing only in merge mode must not.
        """

        layers = [
            ConfigLayer("base", LayerPhase.BASE, {"merged": {"a": 1}, "replaced": {"a": 1}}),
            ConfigLayer("over", LayerPhase.OVERLAY, {"merged": {"b": 2}, "replaced": {"b": 2}}),
        ]
        result = resolve(
            "config.v1",
            {
                "merged": FieldSpec(FieldKind.MAP, MergeMode.MAP_MERGE),
                "replaced": FieldSpec(FieldKind.MAP, MergeMode.REPLACE),
            },
            layers,
        )
        self.assertEqual(result.effective["merged"], {"a": 1, "b": 2})
        self.assertEqual(result.effective["replaced"], {"b": 2})

    def test_append_concatenates_rather_than_discarding(self) -> None:
        result = resolve(
            "config.v1",
            {"steps": FieldSpec(FieldKind.SEQUENCE, MergeMode.APPEND)},
            [
                ConfigLayer("base", LayerPhase.BASE, {"steps": ["fetch"]}),
                ConfigLayer("over", LayerPhase.OVERLAY, {"steps": ["train"]}),
            ],
        )
        self.assertEqual(result.effective["steps"], ["fetch", "train"])

    def test_a_required_field_left_unset_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve(
                "config.v1",
                {
                    "endpoint": FieldSpec(FieldKind.STRING, required=True),
                    "retries": FieldSpec(FieldKind.INTEGER, required=True),
                },
                [ConfigLayer("base", LayerPhase.BASE, {"endpoint": "https://api.example"})],
            )

    def test_an_undeclared_field_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve(
                "config.v1",
                {"token": FieldSpec(FieldKind.SECRET_REF, required=True, sensitive=True)},
                [ConfigLayer("code-defaults", LayerPhase.DEFAULTS, {"undeclared": True})],
            )


if __name__ == "__main__":
    unittest.main()
