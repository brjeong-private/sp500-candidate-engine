from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sp500_candidate_engine.analytics.source_repository import SourceRepository
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.llm_preselection.config import LlmPreselectionConfig

_NEWS_METADATA_FIELDS = (
    "description",
    "author",
    "keywords",
    "publisher",
    "insights",
)
_EARNINGS_EVENT_TYPE = "EARNINGS"
_NEWS_EVENT_TYPE = "NEWS"


def _json_value(value: object) -> object:
    if isinstance(value, (date, datetime, uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _selected_metadata(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        field: _bounded_metadata_value(value[field])
        for field in _NEWS_METADATA_FIELDS
        if field in value and value[field] not in (None, "", [])
    }


def _bounded_metadata_value(value: object) -> object:
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, dict):
        return {
            str(key): _bounded_metadata_value(item)
            for key, item in list(
                sorted(value.items(), key=lambda pair: str(pair[0]))
            )[:20]
        }
    if isinstance(value, (list, tuple)):
        return [_bounded_metadata_value(item) for item in value[:20]]
    return _json_value(value)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("Evidence timestamp must be a datetime")
    return value


def _event_at(row: dict[str, object]) -> datetime:
    return _timestamp(
        row.get("published_at") or row.get("scheduled_at") or row["source_available_at"]
    )


def _period_end(row: dict[str, object]) -> date:
    value = row["period_end"]
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError("Fact period end must be a date")
    return value


def _price_number(value: object) -> float:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        raise TypeError("Price context requires numeric values")
    return float(value)


def _volume(value: object) -> int:
    if type(value) is not int:
        raise TypeError("Volume must be an integer")
    return value


@dataclass(frozen=True)
class EvidenceLink:
    evidence_link_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    source_kind: str
    entity_key: str
    source_available_at: datetime
    observed_at: datetime | None
    event_at: datetime | None
    citation_id: uuid.UUID | None = None


@dataclass(frozen=True)
class EvidencePacket:
    instrument_id: uuid.UUID
    issuer_id: uuid.UUID
    symbol: str
    company_name: str
    sector: str | None
    packet: dict[str, object]
    packet_hash: str
    estimated_tokens: int
    section_counts: dict[str, int]
    missing_sections: tuple[str, ...]
    truncated_sections: tuple[str, ...]
    links: tuple[EvidenceLink, ...]
    screening_links: tuple[EvidenceLink, ...] = ()


class EvidencePacketBuilder:
    def __init__(
        self,
        repository: SourceRepository,
        config: LlmPreselectionConfig,
    ) -> None:
        self.repository = repository
        self.config = config
        self.screening_audit: tuple[dict[str, object], ...] = ()

    def build_all(
        self,
        *,
        execution_context_id: uuid.UUID,
        target_session: date,
    ) -> tuple[EvidencePacket, ...]:
        self.repository.validate_context_manifest(
            execution_context_id=execution_context_id
        )
        context = self.repository.read_context(
            execution_context_id=execution_context_id
        )
        cutoff_at = context["cutoff_at"]
        if not isinstance(cutoff_at, datetime):
            raise TypeError("execution context cutoff_at must be datetime")
        members = self.repository.read_universe_members(
            execution_context_id=execution_context_id,
            target_session=target_session,
        )
        if self.config.event_policy:
            from sp500_candidate_engine.selection.eligibility import read_selection_eligibility

            members, gates = read_selection_eligibility(
                self.repository, execution_context_id=execution_context_id,
                target_session=target_session,
            )
            members = [member for member in members if not gates[uuid.UUID(
                str(member["instrument_id"])
            )]]
        bar_rows = [] if self.config.event_policy else self.repository.read_bars(
            execution_context_id=execution_context_id,
            start_date=target_session - timedelta(days=150),
            end_date=target_session,
        )
        bars_by_instrument: dict[uuid.UUID, list[dict[str, object]]] = defaultdict(list)
        for row in bar_rows:
            bars_by_instrument[uuid.UUID(str(row["instrument_id"]))].append(row)
        packets = tuple(
            self._build_one(
                execution_context_id=execution_context_id,
                target_session=target_session,
                cutoff_at=cutoff_at,
                member=member,
                bars=bars_by_instrument[uuid.UUID(str(member["instrument_id"]))],
            )
            for member in members
        )
        from sp500_candidate_engine.llm_preselection.temporal import validate_packet

        for packet in packets:
            validate_packet(
                packet, cutoff_at=cutoff_at, target_session=target_session,
                execution_context_id=execution_context_id if self.config.event_policy else None,
                knowledge_mode=str(context["knowledge_mode"]),
            )
        if self.config.screening is not None:
            from sp500_candidate_engine.llm_preselection.screening import screen_packets

            screened = screen_packets(
                packets, execution_context_id=execution_context_id, cutoff_at=cutoff_at,
                policy_version=self.config.policy_version, config=self.config.screening,
                knowledge_mode=str(context["knowledge_mode"]),
            )
            packets = screened.packets
            self.screening_audit = screened.audit
        total_tokens = sum(packet.estimated_tokens for packet in packets)
        if total_tokens > self.config.limits.total_input_tokens:
            raise ValueError(
                "LLM evidence token budget exceeded: "
                f"{total_tokens}>{self.config.limits.total_input_tokens}"
            )
        return packets

    def _build_one(
        self,
        *,
        execution_context_id: uuid.UUID,
        target_session: date,
        cutoff_at: datetime,
        member: dict[str, object],
        bars: list[dict[str, object]],
    ) -> EvidencePacket:
        instrument_id = uuid.UUID(str(member["instrument_id"]))
        issuer_id = uuid.UUID(str(member["issuer_id"]))
        news = self.repository.read_events(
            execution_context_id=execution_context_id,
            instrument_id=instrument_id,
            event_type=_NEWS_EVENT_TYPE,
            start_at=cutoff_at - timedelta(days=self.config.windows.news_days),
            clock="AVAILABLE" if self.config.event_policy else "EVENT",
        )
        earnings = self.repository.read_events(
            execution_context_id=execution_context_id,
            instrument_id=instrument_id,
            event_type=_EARNINGS_EVENT_TYPE,
            start_at=cutoff_at - timedelta(days=730),
        )
        if not self.config.event_policy:
            earnings = earnings[:self.config.windows.earnings_events]
        other_events: list[dict[str, object]] = []
        if self.config.screening is not None:
            recent = self.repository.read_events(
                execution_context_id=execution_context_id, instrument_id=instrument_id,
                event_type=_EARNINGS_EVENT_TYPE,
                start_at=cutoff_at - timedelta(days=self.config.screening.lookback_days),
                clock="AVAILABLE",
            )
            upcoming = self.repository.read_events(
                execution_context_id=execution_context_id, instrument_id=instrument_id,
                event_type=_EARNINGS_EVENT_TYPE,
                start_at=cutoff_at - timedelta(days=self.config.screening.earnings_window_days),
                end_at=cutoff_at + timedelta(days=self.config.screening.earnings_window_days),
                clock="SCHEDULE",
            )
            earnings = list({
                str(row["event_revision_id"]): row for row in [*recent, *upcoming, *earnings]
            }.values())
            other_events = self.repository.read_events(
                execution_context_id=execution_context_id, instrument_id=instrument_id,
                event_type="CORPORATE_EVENT",
                start_at=cutoff_at - timedelta(days=self.config.windows.corporate_actions_days),
                clock="AVAILABLE",
            )
        filings = self.repository.read_sec_filings(
            execution_context_id=execution_context_id,
            issuer_id=issuer_id,
            filed_on_or_after=target_session
            - timedelta(days=self.config.windows.filings_days),
        )
        facts = self.repository.read_sec_facts(
            execution_context_id=execution_context_id,
            issuer_id=issuer_id,
            period_end_on_or_before=target_session,
        )
        period_ends = sorted(
            {_period_end(row) for row in facts},
            reverse=True,
        )[: self.config.windows.fact_quarters]
        screening_facts = facts
        facts = [row for row in facts if _period_end(row) in period_ends]
        actions = self.repository.read_corporate_actions(
            execution_context_id=execution_context_id,
            instrument_id=instrument_id,
            start_date=target_session
            - timedelta(days=self.config.windows.corporate_actions_days),
            end_date=target_session,
        )
        screening_links = (
            self._links(
                member, news,
                [{**row, "published_at": None} if row.get("scheduled_at") else row
                 for row in earnings],
                [{**row, "source_available_at": row["accepted_at"]} for row in filings],
                screening_facts, actions, [],
            )
            + self._other_event_links(member, other_events)
            if self.config.event_policy else ()
        )
        bars = [] if self.config.event_policy else bars[-self.config.windows.price_sessions :]

        truncated: list[str] = []
        news = self._limit(news, self.config.limits.news_items, "news", truncated)
        earnings = self._limit(
            earnings, self.config.windows.earnings_events, "earnings", truncated
        )
        filings = self._limit(
            filings, self.config.limits.filings, "filings", truncated
        )
        facts = self._limit(facts, self.config.limits.facts, "facts", truncated)
        actions = self._limit(
            actions,
            self.config.limits.corporate_actions,
            "corporate_actions",
            truncated,
        )
        sections = {
            "news": [self._news_item(row) for row in news],
            "earnings": [self._event_item(row) for row in earnings],
            "filings": [self._filing_item(row) for row in filings],
            "facts": [self._fact_item(row) for row in facts],
            "corporate_actions": [self._action_item(row) for row in actions],
            "price_context": self._price_context(bars),
        }
        if self.config.event_policy:
            sections.pop("price_context")
            other_events = self._limit(
                other_events, self.config.limits.corporate_actions, "events", truncated
            )
            sections["events"] = [self._event_item(row) for row in other_events]
        section_counts = {
            key: len(value) if isinstance(value, list) else int(bool(value))
            for key, value in sections.items()
        }
        missing = tuple(key for key, count in section_counts.items() if count == 0)
        packet = {
            "schema_version": self.config.evidence_schema_version,
            "target_session": target_session.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
            "identity": {
                "instrument_id": str(instrument_id),
                "issuer_id": str(issuer_id),
                "symbol": str(member["symbol"]),
                "company_name": str(member["security_name"]),
                "sector": member.get("sector"),
                "sub_industry": member.get("sub_industry"),
                "primary_exchange": member.get("primary_exchange"),
                "instrument_status": member.get("instrument_status"),
            },
            **sections,
            "missing_sections": list(missing),
            "truncated_sections": sorted(truncated),
        }
        if self.config.event_policy:
            packet["execution_context_id"] = str(execution_context_id)
        if self.config.enrichment is not None:
            packet["identity"]["cik"] = self.repository.read_issuer_cik(issuer_id=issuer_id)
        packet = _json_value(packet)  # type: ignore[assignment]
        assert isinstance(packet, dict)
        encoded = json.dumps(
            packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        base_budget = self.config.limits.packet_characters - (
            self.config.enrichment.reserved_characters if self.config.enrichment else 0
        )
        if self.config.event_policy:
            raw_sections = {
                "news": news, "earnings": earnings, "filings": filings,
                "facts": facts, "corporate_actions": actions, "events": other_events,
            }
            while len(encoded) > base_budget:
                nonempty = [key for key, values in raw_sections.items() if values]
                if not nonempty:
                    break
                section = max(nonempty, key=lambda key: (
                    len(json.dumps(packet[key], ensure_ascii=True)), key,
                ))
                raw_sections[section].pop()
                items = packet[section]
                if not isinstance(items, list):
                    raise TypeError("Evidence sections must be lists")
                items.pop()
                if section not in truncated:
                    truncated.append(section)
                section_counts[section] = len(items)
                missing = tuple(key for key, count in section_counts.items() if count == 0)
                packet["missing_sections"] = list(missing)
                packet["truncated_sections"] = sorted(truncated)
                encoded = json.dumps(
                    packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                )
        if len(encoded) > base_budget:
            raise ValueError(
                f"Evidence packet exceeds character budget for {instrument_id}"
            )
        links = self._links(member, news, earnings, filings, facts, actions, bars)
        links += self._other_event_links(member, other_events)
        return EvidencePacket(
            instrument_id=instrument_id,
            issuer_id=issuer_id,
            symbol=str(member["symbol"]),
            company_name=str(member["security_name"]),
            sector=None if member.get("sector") is None else str(member["sector"]),
            packet=packet,
            packet_hash=_canonical_hash(packet),
            estimated_tokens=(len(encoded) + 3) // 4,
            section_counts=section_counts,
            missing_sections=missing,
            truncated_sections=tuple(sorted(truncated)),
            links=links,
            screening_links=screening_links,
        )

    @staticmethod
    def _other_event_links(
        member: dict[str, object], events: list[dict[str, object]]
    ) -> tuple[EvidenceLink, ...]:
        return tuple(
            EvidenceLink(
                _stable_uuid("llm-evidence-link", (
                    f"{member['instrument_id']}:EVENT:{row['event_revision_id']}:"
                    f"{row['source_snapshot_id']}"
                )),
                uuid.UUID(str(row["source_snapshot_id"])), "EVENT",
                str(row["event_revision_id"]), _timestamp(row["source_available_at"]),
                _timestamp(row["observed_at"]) if row.get("observed_at") is not None else None,
                _event_at(row),
            )
            for row in events
        )

    @staticmethod
    def _limit(
        rows: list[dict[str, object]],
        maximum: int,
        section: str,
        truncated: list[str],
    ) -> list[dict[str, object]]:
        if len(rows) > maximum:
            truncated.append(section)
        return rows[:maximum]

    @staticmethod
    def _news_item(row: dict[str, object]) -> dict[str, object]:
        return {
            "event_revision_id": str(row["event_revision_id"]),
            "title": str(row["title"])[:1000],
            "published_at": _json_value(row.get("published_at")),
            "metadata": _selected_metadata(row.get("metadata")),
        }

    @staticmethod
    def _event_item(row: dict[str, object]) -> dict[str, object]:
        metadata = row.get("metadata")
        return {
            "event_revision_id": str(row["event_revision_id"]),
            "title": str(row["title"])[:1000],
            "scheduled_at": _json_value(row.get("scheduled_at")),
            "metadata": _json_value(metadata) if isinstance(metadata, dict) else {},
        }

    @staticmethod
    def _filing_item(row: dict[str, object]) -> dict[str, object]:
        return {
            key: _json_value(row.get(key))
            for key in (
                "filing_id",
                "accession_no",
                "form_type",
                "period_end",
                "filed_date",
                "accepted_at",
                "is_amendment",
            )
        }

    @staticmethod
    def _fact_item(row: dict[str, object]) -> dict[str, object]:
        return {
            key: _json_value(row.get(key))
            for key in (
                "fact_id",
                "filing_id",
                "taxonomy",
                "concept",
                "unit",
                "period_start",
                "period_end",
                "value_numeric",
                "fiscal_year",
                "fiscal_period",
                "frame",
            )
        }

    @staticmethod
    def _action_item(row: dict[str, object]) -> dict[str, object]:
        return {
            key: _json_value(row.get(key))
            for key in (
                "action_id",
                "action_type",
                "effective_date",
                "declaration_date",
                "record_date",
                "pay_date",
                "cash_amount",
                "currency",
                "split_from",
                "split_to",
            )
        }

    @staticmethod
    def _price_context(rows: list[dict[str, object]]) -> dict[str, object]:
        if not rows:
            return {}
        closes = [
            _price_number(row["adjusted_close"] or row["close"])
            for row in rows
        ]
        volumes = [_volume(row["volume"]) for row in rows]
        returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(1, len(closes))
            if closes[index - 1] > 0
        ]
        mean_return = sum(returns) / len(returns) if returns else 0.0
        variance = (
            sum((value - mean_return) ** 2 for value in returns) / len(returns)
            if returns
            else 0.0
        )
        return {
            "session_count": len(rows),
            "start_session": str(rows[0]["session_date"]),
            "end_session": str(rows[-1]["session_date"]),
            "last_close": closes[-1],
            "total_return": closes[-1] / closes[0] - 1 if closes[0] > 0 else None,
            "daily_volatility": variance**0.5,
            "average_volume": sum(volumes) / len(volumes),
        }

    @staticmethod
    def _links(
        member: dict[str, object],
        news: list[dict[str, object]],
        earnings: list[dict[str, object]],
        filings: list[dict[str, object]],
        facts: list[dict[str, object]],
        actions: list[dict[str, object]],
        bars: list[dict[str, object]],
    ) -> tuple[EvidenceLink, ...]:
        rows: list[tuple[str, str, dict[str, object], datetime | None]] = [
            (
                "UNIVERSE",
                str(member["universe_version_id"]),
                {
                    "source_snapshot_id": member["universe_snapshot_id"],
                    "source_available_at": member["universe_source_available_at"],
                    "observed_at": None,
                },
                member.get("effective_at"),  # type: ignore[arg-type]
            ),
            (
                "INSTRUMENT_STATE",
                str(member["instrument_state_id"]),
                {
                    "source_snapshot_id": member["state_snapshot_id"],
                    "source_available_at": member["source_available_at"],
                    "observed_at": member.get("observed_at"),
                },
                None,
            ),
        ]
        for kind, items, key in (
            ("NEWS", news, "event_revision_id"),
            ("EARNINGS", earnings, "event_revision_id"),
            ("SEC_FILING", filings, "filing_id"),
            ("SEC_FACT", facts, "fact_id"),
            ("CORPORATE_ACTION", actions, "action_id"),
        ):
            rows.extend(
                (kind, str(row[key]), row, _event_at(row) if "event_revision_id" in row else None)
                for row in items
            )
        rows.extend(
            (
                "DAILY_BAR",
                f"{row['instrument_id']}:{row['session_date']}:{row['source_id']}:{row['revision_no']}",
                row,
                None,
            )
            for row in bars
        )
        links = []
        instrument_id = str(member["instrument_id"])
        for kind, entity_key, row, event_at in rows:
            snapshot_id = uuid.UUID(str(row["source_snapshot_id"]))
            fingerprint = f"{instrument_id}:{kind}:{entity_key}:{snapshot_id}"
            links.append(
                EvidenceLink(
                    evidence_link_id=_stable_uuid("llm-evidence-link", fingerprint),
                    source_snapshot_id=snapshot_id,
                    source_kind=kind,
                    entity_key=entity_key,
                    source_available_at=row["source_available_at"],  # type: ignore[arg-type]
                    observed_at=row.get("observed_at"),  # type: ignore[arg-type]
                    event_at=event_at,
                )
            )
        return tuple(links)
