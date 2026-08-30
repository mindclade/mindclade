from dataclasses import dataclass


@dataclass(frozen=True)
class SecretRef:
    provider: str
    logical_name: str
    version_policy: str


def redact(v: SecretRef):
    return {
        "redacted": True,
        "secret_ref": {
            "provider": v.provider,
            "logical_name": v.logical_name,
            "version_policy": v.version_policy,
        },
    }
