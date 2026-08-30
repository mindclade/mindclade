from collections.abc import Mapping


def validate_metric_attributes(attributes: Mapping[str, str]) -> None:
    if len(attributes) > 16:
        raise ValueError("too many attributes")
