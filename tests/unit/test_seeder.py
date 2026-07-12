from dataclasses import dataclass
from pathlib import Path

from aftwin.netbox.client import Record
from aftwin.netbox.fixture import load_fixture
from aftwin.netbox.seeder import NetBoxSeeder


@dataclass
class FakeRecord:
    id: int

    def serialize(self) -> dict[str, object]:
        return {"id": self.id}


class FakeClient:
    def __init__(self) -> None:
        self.records: dict[tuple[str, tuple[tuple[str, object], ...]], FakeRecord] = {}

    def ensure(
        self, path: str, lookup: dict[str, object], values: dict[str, object]
    ) -> tuple[Record, bool]:
        del values
        key = (path, tuple(sorted(lookup.items())))
        if key in self.records:
            return self.records[key], False
        record = FakeRecord(id=len(self.records) + 1)
        self.records[key] = record
        return record, True


def test_seed_is_idempotent() -> None:
    fixture = load_fixture(Path("fixtures/smoke.yaml"))
    client = FakeClient()
    seeder = NetBoxSeeder(client)

    first = seeder.seed(fixture)
    first_created = first.created
    second = seeder.seed(fixture)

    assert first_created > 0
    assert second.created == 0
    assert second.existing == first_created
