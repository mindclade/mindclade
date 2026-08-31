"""Errors raised by the declarative kernel contract API."""

from __future__ import annotations


class KernelContractError(ValueError):
    """Base class for invalid declarative kernel contracts."""


class SchemaError(KernelContractError):
    """A PyTorch schema is malformed or contradicts declared metadata."""


class ExpressionError(KernelContractError):
    """Base class for expression failures."""


class ExpressionValidationError(ExpressionError):
    """An expression was constructed with an invalid or unsafe value."""


class ExpressionDecodeError(ExpressionError):
    """Serialized expression data was not part of the supported language."""


class ExpressionEvaluationError(ExpressionError):
    """An expression could not be evaluated against supplied metadata."""


class ExpressionCodegenError(ExpressionError):
    """An expression cannot be represented by the requested validator target."""
