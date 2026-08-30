"""Fail-closed Buildkite context validation for the GitHub dispatch bridge."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{8,200}$")
LAUNCHER_IDENTITY_PATTERN = re.compile(r"^buildkite://[a-z0-9][a-z0-9._/-]{7,255}$")


@dataclass(frozen=True)
class TrustedContext:
    source_revision: str
    pipeline_definition_revision: str
    pipeline_class: str
    execution_tier: str
    source_trust: str
    correlation_id: str
    context_digest: str
    launcher_revision: str
    launcher_digest: str
    launcher_identity: str
    cache_mode: str
    cache_platform: str
    cache_architecture: str
    cache_toolchain_digest: str
    cache_build_mode: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> TrustedContext:
        values = os.environ if environment is None else environment

        def required(name: str) -> str:
            value = values.get(name, "")
            if not value:
                raise ValueError(f"missing required trusted-context value: {name}")
            return value

        context = cls(
            source_revision=required("MINDCLADE_SOURCE_REVISION"),
            pipeline_definition_revision=required("MINDCLADE_PIPELINE_DEFINITION_REVISION"),
            pipeline_class=required("MINDCLADE_PIPELINE_CLASS"),
            execution_tier=required("MINDCLADE_EXECUTION_TIER"),
            source_trust=required("MINDCLADE_SOURCE_TRUST"),
            correlation_id=required("MINDCLADE_CORRELATION_ID"),
            context_digest=required("MINDCLADE_CONTEXT_DIGEST"),
            launcher_revision=required("MINDCLADE_LAUNCHER_REVISION"),
            launcher_digest=required("MINDCLADE_LAUNCHER_DIGEST"),
            launcher_identity=required("MINDCLADE_LAUNCHER_IDENTITY"),
            cache_mode=required("MINDCLADE_CACHE_MODE"),
            cache_platform=required("MINDCLADE_CACHE_PLATFORM"),
            cache_architecture=required("MINDCLADE_CACHE_ARCHITECTURE"),
            cache_toolchain_digest=required("MINDCLADE_CACHE_TOOLCHAIN_DIGEST"),
            cache_build_mode=required("MINDCLADE_CACHE_BUILD_MODE"),
        )
        context.validate()
        return context

    @classmethod
    def for_test(cls, pipeline_class: str) -> TrustedContext:
        execution_tier = "release" if pipeline_class == "release" else "trusted"
        if pipeline_class == "presubmit":
            execution_tier = "untrusted"
        return cls(
            source_revision="a" * 40,
            pipeline_definition_revision="b" * 40 if pipeline_class == "presubmit" else "a" * 40,
            pipeline_class=pipeline_class,
            execution_tier=execution_tier,
            source_trust="untrusted" if pipeline_class == "presubmit" else "protected",
            correlation_id="wave0-pipeline-self-test",
            context_digest="sha256:" + "c" * 64,
            launcher_revision="d" * 40,
            launcher_digest="sha256:" + "e" * 64,
            launcher_identity="buildkite://mindclade/protected-launcher",
            cache_mode="disabled",
            cache_platform="linux",
            cache_architecture="x86_64",
            cache_toolchain_digest="sha256:" + "f" * 64,
            cache_build_mode=pipeline_class,
        )

    def validate(self) -> None:
        if not SHA_PATTERN.fullmatch(self.source_revision):
            raise ValueError("source revision must be one full lowercase Git SHA")
        if not SHA_PATTERN.fullmatch(self.pipeline_definition_revision):
            raise ValueError("pipeline definition revision must be one full lowercase Git SHA")
        if not DIGEST_PATTERN.fullmatch(self.context_digest):
            raise ValueError("trusted-context digest must be a canonical SHA-256 digest")
        if not SHA_PATTERN.fullmatch(self.launcher_revision):
            raise ValueError("launcher revision must be one full lowercase Git SHA")
        if not DIGEST_PATTERN.fullmatch(self.launcher_digest):
            raise ValueError("launcher digest must be a canonical SHA-256 digest")
        if not LAUNCHER_IDENTITY_PATTERN.fullmatch(self.launcher_identity):
            raise ValueError("launcher identity must be a canonical buildkite:// identity")
        if self.cache_mode != "disabled":
            raise ValueError("remote cache mode is not activated by source policy")
        for value, field in (
            (self.cache_platform, "platform"),
            (self.cache_architecture, "architecture"),
        ):
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", value):
                raise ValueError(f"cache {field} is not canonical")
        if not DIGEST_PATTERN.fullmatch(self.cache_toolchain_digest):
            raise ValueError("cache toolchain digest must be canonical")
        if self.cache_build_mode != self.pipeline_class:
            raise ValueError("cache build mode must match the pipeline class")
        if not CORRELATION_PATTERN.fullmatch(self.correlation_id):
            raise ValueError("correlation ID has an invalid format")
        if self.pipeline_class not in {
            "presubmit",
            "protected",
            "nightly",
            "gpu",
            "release",
            "security",
        }:
            raise ValueError("pipeline class is not allowlisted")
        if self.execution_tier not in {"untrusted", "trusted", "release"}:
            raise ValueError("execution tier is not allowlisted")
        if self.source_trust not in {"untrusted", "trusted", "protected"}:
            raise ValueError("source trust is not allowlisted")
        if self.pipeline_class == "presubmit":
            if self.execution_tier != "untrusted":
                raise ValueError("presubmit must use the isolated untrusted tier")
            if self.source_trust not in {"untrusted", "trusted", "protected"}:
                raise ValueError("presubmit source trust is not allowlisted")
        elif self.pipeline_class == "release":
            if (
                self.execution_tier != "release"
                or self.source_trust != "protected"
                or self.source_revision != self.pipeline_definition_revision
            ):
                raise ValueError("release requires a revision-identical release tier")
        elif self.execution_tier not in {"trusted", "release"}:
            raise ValueError("protected pipeline class requires a protected execution tier")
        elif self.source_trust != "protected":
            raise ValueError("protected pipeline class requires protected source trust")
        elif self.source_revision != self.pipeline_definition_revision:
            raise ValueError("protected pipeline must execute its own exact definition revision")

    def pipeline_environment(self) -> dict[str, str]:
        return {
            "MINDCLADE_CONTEXT_DIGEST": self.context_digest,
            "MINDCLADE_CORRELATION_ID": self.correlation_id,
            "MINDCLADE_EXECUTION_TIER": self.execution_tier,
            "MINDCLADE_PIPELINE_CLASS": self.pipeline_class,
            "MINDCLADE_PIPELINE_DEFINITION_REVISION": self.pipeline_definition_revision,
            "MINDCLADE_SOURCE_REVISION": self.source_revision,
            "MINDCLADE_SOURCE_TRUST": self.source_trust,
            "MINDCLADE_LAUNCHER_REVISION": self.launcher_revision,
            "MINDCLADE_LAUNCHER_DIGEST": self.launcher_digest,
            "MINDCLADE_LAUNCHER_IDENTITY": self.launcher_identity,
            "MINDCLADE_CACHE_MODE": self.cache_mode,
            "MINDCLADE_CACHE_PLATFORM": self.cache_platform,
            "MINDCLADE_CACHE_ARCHITECTURE": self.cache_architecture,
            "MINDCLADE_CACHE_TOOLCHAIN_DIGEST": self.cache_toolchain_digest,
            "MINDCLADE_CACHE_BUILD_MODE": self.cache_build_mode,
        }
