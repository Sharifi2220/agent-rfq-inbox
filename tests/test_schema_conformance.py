"""The bundled subset interpreter must agree with the reference jsonschema library."""

from __future__ import annotations

import copy
from typing import Any, Iterator

import pytest

jsonschema = pytest.importorskip("jsonschema")

from openquote_lite.schema_engine import SchemaError, load_schema, validate  # noqa: E402

from .conftest import BASE_REQUEST, example_profile_data  # noqa: E402

SCHEMAS = ("quote-request.schema.json", "provider-profile.schema.json", "responses.schema.json")


@pytest.mark.parametrize("name", SCHEMAS)
def test_schemas_are_valid_draft_2020_12(name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(load_schema(name))


def _paths(document: Any, prefix: tuple = ()) -> Iterator[tuple]:
    if isinstance(document, dict):
        for key, value in document.items():
            yield prefix + (key,)
            yield from _paths(value, prefix + (key,))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            yield prefix + (index,)
            yield from _paths(value, prefix + (index,))


def _set(document: Any, path: tuple, value: Any) -> Any:
    clone = copy.deepcopy(document)
    target = clone
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    return clone


def _delete(document: Any, path: tuple) -> Any:
    clone = copy.deepcopy(document)
    target = clone
    for step in path[:-1]:
        target = target[step]
    del target[path[-1]]
    return clone


REPLACEMENTS = [
    None, True, False, 0, 1, 1.0, 1.5, -1, 1899, 2101, "", "x", "a" * 5000, "1100\n", "AT\n", [], [1], {},
    "1100", "at", "AUT", "email", "phone", "quote", "flexible", "emergency", "0.2", "0.1", "short",
    "6f1c9e2a-4b7d-4e0a-9c3e-2f8d1a5b7c90", "https://example.org", "http://example.org", "P2D", "P2X", "de-AT",
]


def _corpus(base: dict[str, Any]) -> Iterator[Any]:
    yield base
    for path in list(_paths(base)):
        yield _delete(base, path)
        for replacement in REPLACEMENTS:
            yield _set(base, path, replacement)
    for path in [()] + [p for p in _paths(base) if isinstance(_get(base, p), dict)]:
        target_value = _get(base, path) if path else base
        if isinstance(target_value, dict):
            yield _set(base, path + ("unexpected",), 1) if path else {**copy.deepcopy(base), "unexpected": 1}


def _get(document: Any, path: tuple) -> Any:
    for step in path:
        document = document[step]
    return document


@pytest.mark.parametrize(
    ("schema_name", "base"),
    [("quote-request.schema.json", BASE_REQUEST), ("provider-profile.schema.json", example_profile_data())],
)
def test_interpreter_matches_reference(schema_name: str, base: dict[str, Any]) -> None:
    schema = load_schema(schema_name)
    reference = jsonschema.Draft202012Validator(schema)
    checked = known_deviation = 0
    for document in _corpus(base):
        issues = validate(document, schema)
        ours = not issues
        theirs = reference.is_valid(document)
        if ours != theirs and not ours and _only_trailing_newline_patterns(document, issues):
            # Known deviation of the reference library: it uses Python's re.search, where
            # '$' also matches before a final newline. JSON Schema prescribes ECMA-262
            # semantics, under which "AT\n" does not match "^[A-Z]{2}$". We follow the spec.
            known_deviation += 1
            continue
        assert ours == theirs, f"disagreement for {document!r}: ours={ours} reference={theirs}"
        checked += 1
    assert checked > 500
    assert known_deviation > 0  # the corpus does exercise the trailing-newline case


def _only_trailing_newline_patterns(document: Any, issues: list) -> bool:
    for issue in issues:
        if issue.code != "pattern":
            return False
        value = document
        for step in issue.path.strip("/").split("/"):
            value = value[int(step)] if isinstance(value, list) else value[step]
        if not (isinstance(value, str) and value.endswith("\n")):
            return False
    return True


def test_unknown_keywords_are_refused() -> None:
    with pytest.raises(SchemaError):
        validate("x", {"type": "string", "format": "email"})
    with pytest.raises(SchemaError):
        validate({}, {"type": "object", "additionalProperties": {"type": "string"}})


def test_boolean_is_not_integer_and_true_is_not_one() -> None:
    assert validate(True, {"type": "integer"})
    assert validate(1, {"const": True})
    assert not validate(2.0, {"type": "integer"})
    assert validate([1, True], {"uniqueItems": True}) == []
    assert validate([1, 1.0], {"uniqueItems": True})


def test_trailing_newline_does_not_pass_anchored_pattern() -> None:
    assert validate("AT\n", {"type": "string", "pattern": "^[A-Z]{2}$"})
    assert not validate("AT", {"type": "string", "pattern": "^[A-Z]{2}$"})
