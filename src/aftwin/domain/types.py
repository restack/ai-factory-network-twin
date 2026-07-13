"""Validated identifiers shared by domain and Git-owned models."""

from typing import Annotated

from pydantic import StringConstraints, TypeAdapter, ValidationError

SafeIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    ),
]

_IDENTIFIER_ADAPTER: TypeAdapter[str] = TypeAdapter(SafeIdentifier)


def validate_identifier(value: str, *, field: str = "identifier") -> str:
    """Validate a path- and Containerlab-safe external identifier."""
    try:
        return _IDENTIFIER_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise ValueError(
            f"{field} must start with an alphanumeric character and contain only "
            "letters, numbers, dots, underscores, or hyphens"
        ) from error
