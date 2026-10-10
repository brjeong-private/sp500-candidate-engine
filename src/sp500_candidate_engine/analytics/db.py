from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class _ManyCursor(Protocol):
    def __enter__(self) -> _ManyCursor: ...

    def __exit__(self, *args: object) -> None: ...

    def executemany(
        self,
        query: str,
        params_seq: Iterable[tuple[object, ...]],
    ) -> object: ...


class ManyConnection(Protocol):
    def cursor(self) -> _ManyCursor: ...


def execute_many(
    connection: ManyConnection,
    query: str,
    rows: Iterable[tuple[object, ...]],
) -> None:
    with connection.cursor() as cursor:
        cursor.executemany(query, rows)
