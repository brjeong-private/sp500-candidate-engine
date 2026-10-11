from __future__ import annotations

from sp500_candidate_engine.database import Database


class ReadRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def fetch(self, sql: str, parameters: list[object]) -> list[dict[str, object]]:
        with self.database.connect() as connection, connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            return connection.execute(sql, parameters).fetchall()
