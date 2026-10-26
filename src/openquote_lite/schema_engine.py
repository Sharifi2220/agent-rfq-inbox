"""A deliberately small JSON Schema (draft 2020-12) subset validator.

The JSON Schema files in ``openquote_lite/schemas`` are the normative
definition of the protocol. This module interprets exactly the keywords those
files use, so the package has no runtime dependencies. The test suite checks
that this interpreter agrees with the reference ``jsonschema`` library on a
corpus of valid and invalid documents.

Supported keywords: type, const, enum, properties, required,
additionalProperties (false only), items, minItems, maxItems, uniqueItems,
minLength, maxLength, pattern, minimum, maximum, plus the annotation keywords
$schema, $id, title, description. Any other keyword raises SchemaError, so a
schema change can never silently weaken validation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

_ANNOTATIONS = frozenset({"$schema", "$id", "title", "description"})
_ASSERTIONS = frozenset(
    {
        "type", "const", "enum", "properties", "required", "additionalProperties",
        "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength",
        "pattern", "minimum", "maximum",
    }
)


class SchemaError(Exception):
    """Raised when a schema uses a keyword this interpreter does not support."""


@dataclass(frozen=True)
class Issue:
    path: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path or "/", "code": self.code, "message": self.message}


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    """Load a bundled schema by file name, e.g. ``quote-request.schema.json``."""
    text = resources.files("openquote_lite").joinpath("schemas", name).read_text("utf-8")
    return json.loads(text)


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    # ECMA-262 '$' (as used by JSON Schema) matches only at the end of the
    # input. Python's '$' also matches before a trailing newline, which would
    # let "value\n" pass an anchored pattern. Translate a final anchor to \Z.
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


def _escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if isinstance(value, bool):
        return False
    if expected == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if expected == "number":
        return isinstance(value, (int, float))
    raise SchemaError(f"unsupported type {expected!r}")


def json_equal(a: Any, b: Any) -> bool:
    """Equality with JSON semantics: true != 1, 1 == 1.0, deep for containers."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def validate(instance: Any, schema: dict[str, Any], path: str = "") -> list[Issue]:
    """Return all issues of ``instance`` against ``schema`` (empty list = valid)."""
    unknown = set(schema) - _ANNOTATIONS - _ASSERTIONS
    if unknown:
        raise SchemaError(f"unsupported schema keywords at {path or '/'}: {sorted(unknown)}")

    issues: list[Issue] = []
    if "const" in schema and not json_equal(instance, schema["const"]):
        issues.append(Issue(path, "const", f"must be {json.dumps(schema['const'])}"))
    if "enum" in schema and not any(json_equal(instance, option) for option in schema["enum"]):
        allowed = ", ".join(json.dumps(option) for option in schema["enum"])
        issues.append(Issue(path, "enum", f"must be one of {allowed}"))
    if "type" in schema and not _is_type(instance, schema["type"]):
        issues.append(Issue(path, "type", f"must be of type {schema['type']}"))
        return issues

    if isinstance(instance, str):
        length = len(instance)
        if "minLength" in schema and length < schema["minLength"]:
            issues.append(Issue(path, "min_length", f"must have at least {schema['minLength']} characters"))
        if "maxLength" in schema and length > schema["maxLength"]:
            issues.append(Issue(path, "max_length", f"must have at most {schema['maxLength']} characters"))
        if "pattern" in schema and _compile(schema["pattern"]).search(instance) is None:
            issues.append(Issue(path, "pattern", "has an invalid format"))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            issues.append(Issue(path, "minimum", f"must be >= {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            issues.append(Issue(path, "maximum", f"must be <= {schema['maximum']}"))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            issues.append(Issue(path, "min_items", f"must have at least {schema['minItems']} items"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            issues.append(Issue(path, "max_items", f"must have at most {schema['maxItems']} items"))
        if schema.get("uniqueItems"):
            for i, item in enumerate(instance):
                if any(json_equal(item, other) for other in instance[:i]):
                    issues.append(Issue(path, "unique_items", "items must be unique"))
                    break
        if "items" in schema:
            for i, item in enumerate(instance):
                issues.extend(validate(item, schema["items"], f"{path}/{i}"))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in instance:
                issues.append(Issue(f"{path}/{_escape(name)}", "required", "is required"))
        additional = schema.get("additionalProperties", True)
        if additional is not False and additional is not True:
            raise SchemaError("only additionalProperties: false is supported")
        for name, value in instance.items():
            child = f"{path}/{_escape(name)}"
            if name in properties:
                issues.extend(validate(value, properties[name], child))
            elif additional is False:
                issues.append(Issue(child, "unknown_field", "is not allowed"))

    return issues
