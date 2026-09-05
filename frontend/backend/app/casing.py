"""snake_case <-> camelCase at the edge.

INTEGRATION.md says the backend sends snake_case and `adapters.ts` maps it. That
stays the canonical contract. But `?case=camel` on any endpoint returns camelCase
directly, which means the console can set DATA_SOURCE="api" and work today, before
the adapters are finished — and it gives us a way to isolate a bug to the adapter
layer in about ten seconds during integration week.

The nested keys used by the domain (contributing_factors, health_sub_scores) are
converted too, because that is what the UI meters read.
"""
from __future__ import annotations

import re
from typing import Any

_snake_re = re.compile(r"_([a-z0-9])")

# Keys whose VALUES are free-form maps we still want converted (UI reads them),
# versus keys we must leave alone (GeoJSON `properties`, model feature names).
PRESERVE_VALUE_KEYS = {"properties", "feature_importance", "metrics", "components"}


def to_camel(s: str) -> str:
    return _snake_re.sub(lambda m: m.group(1).upper(), s)


def to_snake(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def camelize(obj: Any, _key: str | None = None) -> Any:
    if isinstance(obj, dict):
        if _key in PRESERVE_VALUE_KEYS:
            return obj
        return {to_camel(k): camelize(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [camelize(v, _key) for v in obj]
    return obj


def snakeize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {to_snake(k): snakeize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [snakeize(v) for v in obj]
    return obj


def shape(payload: Any, case: str | None) -> Any:
    """Apply the requested case. Default (None / 'snake') is the canonical contract."""
    if case and case.lower() in ("camel", "camelcase"):
        return camelize(payload)
    return payload
