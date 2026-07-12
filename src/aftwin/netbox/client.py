"""Small typed boundary around pynetbox's dynamic API."""

from collections.abc import Iterable
from typing import Protocol, cast

import pynetbox  # type: ignore[reportMissingTypeStubs]
from pydantic import SecretStr

from aftwin.errors import NetBoxOperationError


class Record(Protocol):
    """Subset of a pynetbox record used by the application."""

    id: int

    def serialize(self) -> dict[str, object]: ...


class Endpoint(Protocol):
    """Subset of a pynetbox endpoint used by the application."""

    def filter(self, **kwargs: object) -> Iterable[Record]: ...

    def create(self, values: dict[str, object]) -> Record: ...


class NetBoxClient:
    """Provide deterministic query and ensure operations without leaking credentials."""

    def __init__(self, url: str, token: SecretStr) -> None:
        self._api: object = pynetbox.api(url.rstrip("/"), token=token.get_secret_value())

    def endpoint(self, path: str) -> Endpoint:
        """Resolve an ``app.endpoint`` path."""
        app_name, endpoint_name = path.split(".", maxsplit=1)
        app = getattr(self._api, app_name)
        return cast(Endpoint, getattr(app, endpoint_name))

    def list(self, path: str, **filters: object) -> list[dict[str, object]]:
        """Return serialized API records sorted by ID."""
        try:
            records = self.endpoint(path).filter(**filters)
            serialized = [record.serialize() for record in records]
            return sorted(serialized, key=_record_id)
        except Exception as error:
            raise NetBoxOperationError(f"query {path}", type(error).__name__) from error

    def one(self, path: str, **filters: object) -> dict[str, object] | None:
        """Return one matching serialized record."""
        records = self.list(path, **filters)
        if len(records) > 1:
            raise NetBoxOperationError(f"query {path}", "multiple records matched a unique lookup")
        return records[0] if records else None

    def ensure(
        self, path: str, lookup: dict[str, object], values: dict[str, object]
    ) -> tuple[Record, bool]:
        """Return an existing object or create it once."""
        try:
            matches = list(self.endpoint(path).filter(**lookup))
            if len(matches) > 1:
                raise NetBoxOperationError(
                    f"ensure {path}", "multiple records matched a unique lookup"
                )
            if matches:
                return matches[0], False
            return self.endpoint(path).create(values), True
        except NetBoxOperationError:
            raise
        except Exception as error:
            raise NetBoxOperationError(f"ensure {path}", type(error).__name__) from error


def _record_id(record: dict[str, object]) -> int:
    value = record.get("id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise NetBoxOperationError("serialize", "record ID is not an integer")
    return value
