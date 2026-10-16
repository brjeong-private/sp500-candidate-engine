"""Provision the weekly training managed identity with least-privilege grants."""

from __future__ import annotations

import argparse
from dataclasses import replace
from uuid import UUID

from psycopg import sql

from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database

READ_SCHEMAS = ("ops", "ref", "market", "fundamental", "event", "selection")
WRITE_SCHEMA = "analytics"
DERIVED_OPS_TABLES = ("input_manifest", "input_manifest_member", "execution_context")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal-id", type=UUID, required=True)
    parser.add_argument("--role", required=True)
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
        else:
            connection.execute(
                "SELECT * FROM pgaadauth_create_principal_with_oid"
                "(%s, %s, 'service', false, false)",
                (args.role, str(args.principal_id)),
            )

    with Database(settings).connect() as connection:
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(settings.pg_database), sql.Identifier(args.role)
            )
        )
        for schema in READ_SCHEMAS:
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(args.role)
                )
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(args.role)
                )
            )
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                    "GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(schema), sql.Identifier(args.role))
            )
        connection.execute(
            sql.SQL("GRANT INSERT ON TABLE {} TO {}").format(
                sql.SQL(", ").join(
                    sql.Identifier("ops", table) for table in DERIVED_OPS_TABLES
                ),
                sql.Identifier(args.role),
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(WRITE_SCHEMA), sql.Identifier(args.role)
            )
        )
        connection.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(sql.Identifier(WRITE_SCHEMA), sql.Identifier(args.role))
        )
        connection.execute(
            sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                sql.Identifier(WRITE_SCHEMA), sql.Identifier(args.role)
            )
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                "GRANT SELECT, INSERT, UPDATE ON TABLES TO {}"
            ).format(sql.Identifier(WRITE_SCHEMA), sql.Identifier(args.role))
        )
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA {} "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(sql.Identifier(WRITE_SCHEMA), sql.Identifier(args.role))
        )
    print("Weekly training Entra identity and least-privilege grants verified.")


if __name__ == "__main__":
    main()
