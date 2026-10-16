"""Grant the backend managed identity data-plane access using the Entra administrator."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from psycopg import sql

from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database

SCHEMAS = ("ops", "ref", "market", "fundamental", "event", "analytics", "selection")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal-id", type=UUID, required=True)
    parser.add_argument("--role", default="web-sp500-candidate-8d0218f4")
    args = parser.parse_args()
    settings = Settings.from_env()
    with Database(replace(settings, pg_database="postgres")).connect() as connection:
        existing = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (args.role,)
        ).fetchone()
        if existing is not None:
            identity = connection.execute(
                "SELECT objectid FROM pgaadauth_list_principals(false) WHERE rolname = %s",
                (args.role,),
            ).fetchone()
            if identity is None or str(identity["objectid"]) != str(args.principal_id):
                raise RuntimeError("Existing database role belongs to a different principal")
        if existing is None:
            connection.execute(
                "SELECT * FROM pgaadauth_create_principal_with_oid"
                "(%s, %s, 'service', false, false)",
                (args.role, str(args.principal_id)),
            )
    with Database(settings).connect() as connection:
        migration_directory = Path(__file__).parents[1] / "sql"
        for name in (
            "017_backend_requests.sql",
            "018_multi_model_support.sql",
            "019_advanced_feature_availability.sql",
            "020_backend_pipeline_idempotency.sql",
            "021_weekly_retraining.sql",
        ):
            connection.execute((migration_directory / name).read_text(encoding="utf-8"))
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(settings.pg_database), sql.Identifier(args.role)
            )
        )
        for schema in SCHEMAS:
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(args.role)
                )
            )
            connection.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(args.role)
                )
            )
            connection.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(args.role)
                )
            )
    print("Backend Entra identity and data-plane grants verified.")


if __name__ == "__main__":
    main()
