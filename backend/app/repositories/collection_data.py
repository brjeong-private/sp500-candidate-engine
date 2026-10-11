from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter

from backend.app.pagination import collection_window, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.schemas.collection_data import CollectionRecord, Dataset
from backend.app.schemas.common import Page

_RECORD = TypeAdapter[CollectionRecord](CollectionRecord)


@dataclass(frozen=True)
class QuerySpec:
    select: str
    tables: str
    semantic_date: str
    keys: tuple[str, ...]
    instrument: str | None = None
    issuer: str | None = None
    ticker: str | None = None
    predicate: str = "TRUE"


def _provenance(
    snapshot: str, available: str, observed: str, revision: str = "NULL::integer"
) -> str:
    return (
        f"{snapshot} AS source_snapshot_id, ds.source_id, ds.code AS source_code, "
        f"{available} AS source_available_at, {observed} AS observed_at, "
        f"{revision} AS revision_no"
    )


def _snapshot_join(snapshot: str) -> str:
    return (
        f" JOIN ops.source_snapshot snap ON snap.source_snapshot_id = {snapshot}"
        " JOIN ops.data_source ds ON ds.source_id = snap.source_id"
    )


def _ticker_join(instrument: str, semantic_date: str) -> str:
    return f"""
        LEFT JOIN LATERAL (
            SELECT ident.id_value AS ticker
            FROM ref.instrument_identifier ident
            WHERE ident.instrument_id = {instrument} AND ident.id_type = 'TICKER'
              AND ident.valid_from <= {semantic_date}
              AND (ident.valid_to IS NULL OR ident.valid_to >= {semantic_date})
            ORDER BY ident.valid_from DESC, ident.revision_no DESC,
                ident.observed_at DESC, ident.identifier_id DESC LIMIT 1
        ) symbol ON TRUE
    """


_BAR = QuerySpec(
    select=(
        "b.instrument_id, i.issuer_id, symbol.ticker, b.session_date, b.open, b.high, "
        "b.low, b.close, b.adjusted_close, b.volume, b.vwap, b.currency, b.source_timestamp, "
        "b.price_adjustment_status, b.volume_adjustment_status, "
        + _provenance(
            "b.source_snapshot_id", "b.source_available_at", "b.observed_at", "b.revision_no"
        )
    ),
    tables="""
        (SELECT DISTINCT ON (instrument_id, session_date, source_id) *
         FROM market.daily_bar
         ORDER BY instrument_id, session_date, source_id, revision_no DESC) b
        JOIN ref.instrument i ON i.instrument_id = b.instrument_id
    """
    + _snapshot_join("b.source_snapshot_id")
    + _ticker_join("b.instrument_id", "b.session_date"),
    semantic_date="b.session_date",
    keys=("b.instrument_id::text", "b.source_id::text"),
    instrument="b.instrument_id",
    issuer="i.issuer_id",
    ticker="symbol.ticker",
)
_ACTION = QuerySpec(
    select=(
        "a.instrument_id, i.issuer_id, symbol.ticker, a.action_id, a.action_type, "
        "a.effective_date, a.declaration_date, a.record_date, a.pay_date, a.cash_amount, "
        "a.currency, a.split_from, a.split_to, "
        + _provenance(
            "a.origin_snapshot_id", "a.source_available_at", "a.observed_at", "a.revision_no"
        )
    ),
    tables="""
        (SELECT DISTINCT ON (source_id, source_action_id) *
         FROM market.corporate_action
         ORDER BY source_id, source_action_id, revision_no DESC) a
        JOIN ref.instrument i ON i.instrument_id = a.instrument_id
    """
    + _snapshot_join("a.origin_snapshot_id")
    + _ticker_join("a.instrument_id", "a.effective_date"),
    semantic_date="a.effective_date",
    keys=("a.action_id::text",),
    instrument="a.instrument_id",
    issuer="i.issuer_id",
    ticker="symbol.ticker",
)


def _event(kind: str, timestamp: str) -> QuerySpec:
    semantic_date = f"(r.{timestamp} AT TIME ZONE 'UTC')::date"
    return QuerySpec(
        select=(
            "e.event_id, r.event_revision_id, e.event_type, ei.instrument_id, i.issuer_id, "
            "symbol.ticker, r.title, r.status, r.scheduled_at, r.published_at, "
            + _provenance(
                "r.origin_snapshot_id", "r.source_available_at", "r.observed_at", "r.revision_no"
            )
        ),
        tables="""
            event.market_event e
            JOIN (SELECT DISTINCT ON (event_id) * FROM event.event_revision
                ORDER BY event_id, revision_no DESC) r USING (event_id)
            LEFT JOIN event.event_instrument ei USING (event_id)
            LEFT JOIN ref.instrument i ON i.instrument_id = ei.instrument_id
        """
        + _snapshot_join("r.origin_snapshot_id")
        + _ticker_join("ei.instrument_id", semantic_date),
        semantic_date=semantic_date,
        keys=("r.event_revision_id::text", "COALESCE(ei.instrument_id::text, '')"),
        instrument="ei.instrument_id",
        issuer="i.issuer_id",
        ticker="symbol.ticker",
        predicate=f"e.event_type = '{kind}'",
    )


_FILING = QuerySpec(
    select=(
        "f.filing_id, f.issuer_id, f.accession_no, f.form_type, f.period_end, f.filed_date, "
        "f.accepted_at, f.is_amendment, "
        + _provenance("f.source_snapshot_id", "snap.source_available_at", "snap.fetched_at")
    ),
    tables="fundamental.sec_filing f" + _snapshot_join("f.source_snapshot_id"),
    semantic_date="f.filed_date",
    keys=("f.filing_id::text",),
    issuer="f.issuer_id",
)
_FACT = QuerySpec(
    select=(
        "f.fact_id, f.filing_id, f.issuer_id, f.taxonomy, f.concept, f.unit, "
        "f.period_start, f.period_end, f.value_numeric, f.decimals, f.fiscal_year, "
        "f.fiscal_period, f.frame, "
        + _provenance("f.source_snapshot_id", "f.source_available_at", "f.observed_at")
    ),
    tables="fundamental.fact f" + _snapshot_join("f.source_snapshot_id"),
    semantic_date="(f.source_available_at AT TIME ZONE 'UTC')::date",
    keys=("f.fact_id::text",),
    issuer="f.issuer_id",
)
_UNIVERSE = QuerySpec(
    select=(
        "m.instrument_id, i.issuer_id, m.symbol AS ticker, v.universe_version_id, "
        "v.universe_id, u.code AS universe_code, v.as_of_date, v.provider_revision_id, "
        "v.announced_at, v.effective_at, m.security_name, m.sector, m.sub_industry, "
        "m.provider_symbol, "
        + _provenance("v.source_snapshot_id", "snap.source_available_at", "snap.fetched_at")
    ),
    tables="""
        ref.universe_member m JOIN ref.universe_version v USING (universe_version_id)
        JOIN ref.universe u USING (universe_id)
        JOIN ref.instrument i ON i.instrument_id = m.instrument_id
    """
    + _snapshot_join("v.source_snapshot_id"),
    semantic_date="v.as_of_date",
    keys=("v.universe_version_id::text", "m.instrument_id::text"),
    instrument="m.instrument_id",
    issuer="i.issuer_id",
    ticker="m.symbol",
)
_SESSION = QuerySpec(
    select=(
        "s.calendar_version, s.exchange_mic, s.session_date, s.open_at, s.close_at, "
        "s.is_early_close, s.status, "
        + _provenance("s.source_snapshot_id", "snap.source_available_at", "snap.fetched_at")
    ),
    tables="ref.exchange_session s" + _snapshot_join("s.source_snapshot_id"),
    semantic_date="s.session_date",
    keys=("s.calendar_version", "s.exchange_mic"),
)

SPECS: dict[Dataset, QuerySpec] = {
    Dataset.DAILY_BARS: _BAR,
    Dataset.CORPORATE_ACTIONS: _ACTION,
    Dataset.NEWS: _event("NEWS", "published_at"),
    Dataset.EARNINGS: _event("EARNINGS", "scheduled_at"),
    Dataset.SEC_FILINGS: _FILING,
    Dataset.SEC_FACTS: _FACT,
    Dataset.UNIVERSE_MEMBERS: _UNIVERSE,
    Dataset.EXCHANGE_SESSIONS: _SESSION,
}


class CollectionDataRepository(ReadRepository):
    def list_records(
        self,
        dataset: Dataset,
        *,
        start_date: date,
        end_date: date,
        ticker: str | None = None,
        instrument_id: UUID | None = None,
        issuer_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[CollectionRecord]:
        page_limit(limit)
        collection_window(start_date, end_date)
        spec = SPECS[dataset]
        if dataset == Dataset.EXCHANGE_SESSIONS and any(
            value is not None for value in (ticker, instrument_id, issuer_id)
        ):
            raise HTTPException(
                422, "Exchange sessions have no ticker/instrument/issuer association"
            )
        filters: dict[str, object] = {
            "dataset": dataset,
            "start": start_date,
            "end": end_date,
            "ticker": ticker,
            "instrument": instrument_id,
            "issuer": issuer_id,
        }
        position = decode_cursor(cursor, dataset.value, filters, len(spec.keys) + 1)
        clauses = [f"{spec.semantic_date} BETWEEN %s AND %s", spec.predicate]
        parameters: list[object] = [start_date, end_date]
        if issuer_id is not None and spec.issuer is not None:
            clauses.append(f"{spec.issuer} = %s")
            parameters.append(issuer_id)
        if spec.instrument is not None:
            for column, value in ((spec.instrument, instrument_id), (spec.ticker, ticker)):
                if column is not None and value is not None:
                    clauses.append(f"{column} = %s")
                    parameters.append(value)
        elif spec.issuer is not None and (ticker is not None or instrument_id is not None):
            identity = [f"fi.issuer_id = {spec.issuer}"]
            if instrument_id is not None:
                identity.append("fi.instrument_id = %s")
                parameters.append(instrument_id)
            if ticker is not None:
                identity.append(f"""
                    EXISTS (SELECT 1 FROM ref.instrument_identifier ident
                        WHERE ident.instrument_id = fi.instrument_id
                          AND ident.id_type = 'TICKER' AND ident.id_value = %s
                          AND ident.valid_from <= {spec.semantic_date}
                          AND (ident.valid_to IS NULL OR ident.valid_to >= {spec.semantic_date}))
                """)
                parameters.append(ticker)
            clauses.append(
                "EXISTS (SELECT 1 FROM ref.instrument fi WHERE " + " AND ".join(identity) + ")"
            )
        key_aliases = [f"_key{index}" for index in range(len(spec.keys))]
        key_select = ", ".join(
            f"{expression} AS {alias}"
            for expression, alias in zip(spec.keys, key_aliases, strict=True)
        )
        boundary = ""
        if position is not None:
            try:
                boundary_date = date.fromisoformat(position[0])
            except ValueError:
                raise HTTPException(422, "Invalid collection cursor") from None
            placeholders = ", ".join(["%s"] * len(key_aliases))
            boundary = (
                f"WHERE (_date < %s OR (_date = %s AND "
                f"({', '.join(key_aliases)}) > ({placeholders})))"
            )
            parameters.extend([boundary_date, boundary_date, *position[1:]])
        parameters.append(limit + 1)
        rows = self.fetch(
            f"""
            WITH records AS (
                SELECT {spec.select}, {spec.semantic_date} AS _date, {key_select}
                FROM {spec.tables} WHERE {" AND ".join(clauses)}
            )
            SELECT * FROM records {boundary}
            ORDER BY _date DESC, {", ".join(alias + " ASC" for alias in key_aliases)}
            LIMIT %s
        """,
            parameters,
        )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                dataset.value,
                filters,
                [str(last["_date"]), *(str(last[alias]) for alias in key_aliases)],
            )
        items: list[CollectionRecord] = []
        for row in rows[:limit]:
            row.pop("_date")
            for alias in key_aliases:
                row.pop(alias)
            row["dataset"] = dataset.value
            items.append(_RECORD.validate_python(row))
        return Page[CollectionRecord](items=items, next_cursor=next_cursor)
