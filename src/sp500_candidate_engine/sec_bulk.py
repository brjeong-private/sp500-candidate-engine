from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from types import MappingProxyType
from typing import Any, Literal
from zipfile import BadZipFile, ZipFile

ALLOWED_FORMS = frozenset({"10-K", "10-Q", "10-K-A", "10-Q-A", "8-K", "8-K-A"})

# Deliberately small: these concepts support the first balance-sheet, income,
# cash-flow, EPS, and share-count screens without admitting issuer extensions.
MVP_US_GAAP_CONCEPTS = frozenset(
    {
        "Assets",
        "CashAndCashEquivalentsAtCarryingValue",
        "EarningsPerShareDiluted",
        "Liabilities",
        "NetCashProvidedByUsedInOperatingActivities",
        "NetIncomeLoss",
        "OperatingIncomeLoss",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "Revenues",
        "SalesRevenueNet",
        "StockholdersEquity",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    }
)

ContextType = Literal["instant", "duration"]


@dataclass(frozen=True, slots=True)
class NormalizedFiling:
    cik: str
    accession: str
    accepted_at: datetime
    period: date | None
    filed: date
    form: str
    primary_document: str | None
    primary_document_url: str | None
    amendment: bool


@dataclass(frozen=True, slots=True)
class NormalizedFact:
    cik: str
    accession: str
    accepted_at: datetime
    taxonomy: str
    concept: str
    value: Decimal
    unit: str
    period_start: date | None
    period_end: date
    context_type: ContextType
    duration_days: int | None
    form: str
    fy: int | None
    fp: str | None
    frame: str | None
    decimals: int | None
    amendment: bool
    context_hash: str

    @property
    def period(self) -> date:
        return self.period_end


@dataclass(frozen=True, slots=True)
class SecBulkResult:
    filings: tuple[NormalizedFiling, ...]
    facts: tuple[NormalizedFact, ...]
    summary: Mapping[str, int]


# Short aliases make the records convenient to use at persistence boundaries.
SecFiling = NormalizedFiling
SecFact = NormalizedFact


def parse_sec_bulk(
    submissions_zip: bytes,
    companyfacts_zip: bytes,
    *,
    allowed_ciks: Collection[str | int],
    cutoff_at: datetime,
    fact_allowlist: Collection[str] = MVP_US_GAAP_CONCEPTS,
) -> SecBulkResult:
    """Parse and normalize SEC bulk archives entirely in memory."""
    cutoff = _utc_cutoff(cutoff_at)
    cik_allowlist = frozenset(_normalize_cik(cik) for cik in allowed_ciks)
    concept_allowlist = frozenset(fact_allowlist)
    counters: dict[str, int] = {
        "submission_files": 0,
        "companyfact_files": 0,
        "filings_seen": 0,
        "filings_included": 0,
        "filings_after_cutoff": 0,
        "facts_seen": 0,
        "facts_included": 0,
        "facts_after_cutoff": 0,
        "duplicate_contexts": 0,
    }

    known_filing_by_accession: dict[str, NormalizedFiling] = {}
    filing_by_accession: dict[str, NormalizedFiling] = {}
    for _, payload in _json_members(submissions_zip):
        counters["submission_files"] += 1
        cik = _payload_cik(payload)
        if cik is None or cik not in cik_allowlist:
            continue
        for raw in _submission_records(payload):
            counters["filings_seen"] += 1
            filing = _normalize_filing(cik, raw)
            if filing is None:
                continue
            known = known_filing_by_accession.get(filing.accession)
            if known is not None and known != filing:
                raise ValueError(f"Conflicting submission records for {filing.accession}")
            known_filing_by_accession[filing.accession] = filing
            if filing.accepted_at > cutoff:
                counters["filings_after_cutoff"] += 1
                continue
            existing = filing_by_accession.get(filing.accession)
            if existing is not None and existing != filing:
                raise ValueError(f"Conflicting submission records for {filing.accession}")
            filing_by_accession[filing.accession] = filing

    counters["filings_included"] = len(filing_by_accession)
    fact_by_context: dict[str, NormalizedFact] = {}
    for _, payload in _json_members(companyfacts_zip):
        counters["companyfact_files"] += 1
        cik = _payload_cik(payload)
        if cik is None or cik not in cik_allowlist:
            continue
        facts = payload.get("facts")
        if not isinstance(facts, dict):
            continue
        taxonomy_facts = facts.get("us-gaap")
        if not isinstance(taxonomy_facts, dict):
            continue
        for concept in sorted(concept_allowlist.intersection(taxonomy_facts)):
            concept_payload = taxonomy_facts[concept]
            if not isinstance(concept_payload, dict):
                continue
            units = concept_payload.get("units")
            if not isinstance(units, dict):
                continue
            for unit in sorted(units):
                observations = units[unit]
                if not isinstance(observations, list):
                    continue
                for raw in observations:
                    counters["facts_seen"] += 1
                    if not isinstance(raw, dict):
                        continue
                    accession = _text(raw.get("accn"))
                    filing = filing_by_accession.get(accession or "")
                    if filing is None:
                        known_filing = known_filing_by_accession.get(accession or "")
                        raw_accepted = _optional_datetime(raw.get("accepted"))
                        if (
                            known_filing is not None
                            and known_filing.accepted_at > cutoff
                            or raw_accepted is not None
                            and raw_accepted > cutoff
                        ):
                            counters["facts_after_cutoff"] += 1
                        continue
                    fact = _normalize_fact(
                        cik=cik,
                        filing=filing,
                        concept=concept,
                        unit=str(unit),
                        raw=raw,
                    )
                    if fact is None:
                        continue
                    existing = fact_by_context.get(fact.context_hash)
                    if existing is not None:
                        if existing != fact:
                            raise ValueError(f"Conflicting facts for context {fact.context_hash}")
                        counters["duplicate_contexts"] += 1
                        continue
                    fact_by_context[fact.context_hash] = fact

    counters["facts_included"] = len(fact_by_context)
    filings = tuple(
        sorted(
            filing_by_accession.values(),
            key=lambda item: (item.accepted_at, item.accession),
        )
    )
    facts = tuple(
        sorted(
            fact_by_context.values(),
            key=lambda item: (
                item.cik,
                item.concept,
                item.period_end,
                item.period_start or date.min,
                item.accession,
                item.unit,
            ),
        )
    )
    return SecBulkResult(
        filings=filings,
        facts=facts,
        summary=MappingProxyType(dict(sorted(counters.items()))),
    )


def normalize_sec_bulk(
    submissions_zip: bytes,
    companyfacts_zip: bytes,
    *,
    allowed_ciks: Collection[str | int],
    cutoff_at: datetime,
    fact_allowlist: Collection[str] = MVP_US_GAAP_CONCEPTS,
) -> SecBulkResult:
    return parse_sec_bulk(
        submissions_zip,
        companyfacts_zip,
        allowed_ciks=allowed_ciks,
        cutoff_at=cutoff_at,
        fact_allowlist=fact_allowlist,
    )


def _json_members(archive: bytes) -> Iterator[tuple[str, dict[str, Any]]]:
    try:
        with ZipFile(BytesIO(archive)) as zip_file:
            for name in sorted(zip_file.namelist()):
                if name.endswith("/") or not name.lower().endswith(".json"):
                    continue
                try:
                    payload = json.loads(zip_file.read(name))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(f"Invalid JSON in SEC archive member {name}") from error
                if not isinstance(payload, dict):
                    raise ValueError(f"SEC archive member {name} must contain an object")
                yield name, payload
    except BadZipFile as error:
        raise ValueError("SEC bulk payload is not a valid ZIP archive") from error


def _submission_records(payload: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return
    recent = filings.get("recent")
    if isinstance(recent, list):
        for record in recent:
            if isinstance(record, dict):
                yield record
        return
    if not isinstance(recent, dict):
        return
    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        return
    for index in range(len(accessions)):
        yield {
            key: values[index] if isinstance(values, list) and index < len(values) else None
            for key, values in recent.items()
        }


def _normalize_filing(cik: str, raw: Mapping[str, Any]) -> NormalizedFiling | None:
    accession = _text(raw.get("accessionNumber") or raw.get("accession"))
    form = _normalize_form(raw.get("form"))
    accepted_at = _optional_datetime(raw.get("acceptanceDateTime") or raw.get("accepted"))
    filed = _optional_date(raw.get("filingDate") or raw.get("filed"))
    if accession is None or form not in ALLOWED_FORMS or accepted_at is None or filed is None:
        return None
    primary_document = _text(raw.get("primaryDocument"))
    accession_path = accession.replace("-", "")
    primary_document_url = (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_path}/{primary_document}"
        if primary_document
        else None
    )
    return NormalizedFiling(
        cik=cik,
        accession=accession,
        accepted_at=accepted_at,
        period=_optional_date(raw.get("reportDate") or raw.get("period")),
        filed=filed,
        form=form,
        primary_document=primary_document,
        primary_document_url=primary_document_url,
        amendment=form.endswith("-A"),
    )


def _normalize_fact(
    *,
    cik: str,
    filing: NormalizedFiling,
    concept: str,
    unit: str,
    raw: Mapping[str, Any],
) -> NormalizedFact | None:
    raw_form = _normalize_form(raw.get("form"))
    if raw_form not in ALLOWED_FORMS or raw_form != filing.form:
        return None
    period_start = _optional_date(raw.get("start"))
    period_end = _optional_date(raw.get("end"))
    value = _decimal(raw.get("val"))
    if period_end is None or value is None:
        return None
    context_type: ContextType = "duration" if period_start is not None else "instant"
    duration_days = (period_end - period_start).days if period_start is not None else None
    fy = _optional_int(raw.get("fy"))
    fp = _text(raw.get("fp"))
    frame = _text(raw.get("frame"))
    decimals = _optional_int(raw.get("decimals"))
    context = {
        "accession": filing.accession,
        "cik": cik,
        "concept": concept,
        "context_type": context_type,
        "form": filing.form,
        "fp": fp,
        "frame": frame,
        "fy": fy,
        "period_end": period_end.isoformat(),
        "period_start": period_start.isoformat() if period_start else None,
        "taxonomy": "us-gaap",
        "unit": unit,
    }
    context_hash = hashlib.sha256(
        json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return NormalizedFact(
        cik=cik,
        accession=filing.accession,
        accepted_at=filing.accepted_at,
        taxonomy="us-gaap",
        concept=concept,
        value=value,
        unit=unit,
        period_start=period_start,
        period_end=period_end,
        context_type=context_type,
        duration_days=duration_days,
        form=filing.form,
        fy=fy,
        fp=fp,
        frame=frame,
        decimals=decimals,
        amendment=filing.amendment,
        context_hash=context_hash,
    )


def _normalize_cik(value: str | int) -> str:
    text = str(value).strip()
    if text.upper().startswith("CIK"):
        text = text[3:]
    if not text.isdigit():
        raise ValueError(f"Invalid CIK: {value!r}")
    return text.zfill(10)


def _payload_cik(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("cik")
    if value is None:
        return None
    try:
        return _normalize_cik(value)
    except ValueError:
        return None


def _normalize_form(value: object) -> str | None:
    text = _text(value)
    return text.upper().replace("/", "-") if text else None


def _utc_cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff_at must be timezone-aware")
    return value.astimezone(UTC)


def _optional_datetime(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(f"{text[:-1]}+00:00")
        else:
            parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_date(value: object) -> date | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
