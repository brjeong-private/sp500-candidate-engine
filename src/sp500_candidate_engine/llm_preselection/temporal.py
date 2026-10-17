from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection.asof import publication_bound
from sp500_candidate_engine.llm_preselection.enrichment_contract import document_from_payload
from sp500_candidate_engine.models import KnowledgeMode, RunSpec
from sp500_candidate_engine.temporal import TemporalFence

if TYPE_CHECKING:
    from sp500_candidate_engine.llm_preselection.evidence import EvidenceLink, EvidencePacket

TEMPORAL_HARNESS_VERSION = "llm-cutoff-v2-ny-day"
SOURCE_SECTIONS = {
    "NEWS": ("news", "event_revision_id"),
    "EARNINGS": ("earnings", "event_revision_id"),
    "EVENT": ("events", "event_revision_id"),
    "SEC_FILING": ("filings", "filing_id"),
    "SEC_FACT": ("facts", "fact_id"),
    "CORPORATE_ACTION": ("corporate_actions", "action_id"),
}


def timestamp(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("LLM evidence requires a timezone-aware timestamp")
    return value


def validate_source_time(
    *,
    source_available_at: object,
    observed_at: object,
    cutoff_at: datetime,
    knowledge_mode: str,
    source_kind: str,
) -> None:
    cutoff_at = timestamp(cutoff_at)
    if knowledge_mode not in {"OPERATIONAL_REPLAY", "HISTORICAL_RECONSTRUCTION"}:
        raise ValueError("Unknown LLM evidence knowledge mode")
    fence = TemporalFence(RunSpec(cutoff_at.date(), cutoff_at, KnowledgeMode(knowledge_mode)))
    if source_kind in SOURCE_SECTIONS or source_kind == "DAILY_BAR":
        publication_bound(source_available_at, cutoff_at)
    else:
        fence.require_source_available(
            timestamp(source_available_at), field="LLM evidence availability"
        )
    if knowledge_mode == "OPERATIONAL_REPLAY":
        if observed_at is None:
            if source_kind != "UNIVERSE":
                raise ValueError("Operational LLM evidence requires observation time")
        else:
            fence.require_observed(timestamp(observed_at), field="LLM evidence observation")


def validate_revision_time(
    *,
    source_kind: str,
    revision_no: object,
    revision_observed_at: object,
    cutoff_at: datetime,
) -> None:
    if source_kind not in {"NEWS", "EARNINGS", "EVENT"}:
        return
    if type(revision_no) is not int or revision_no < 1:
        raise ValueError("LLM event evidence has no authoritative revision")
    if revision_no > 1:
        publication_bound(revision_observed_at, cutoff_at)


def provided_item(packet: dict[str, object], source_kind: str, entity_key: str) -> dict:
    section, key = SOURCE_SECTIONS[source_kind]
    matches = [item for item in section_items(packet, section) if str(item.get(key)) == entity_key]
    if len(matches) != 1:
        raise ValueError("LLM evidence is not uniquely present in the provided packet")
    return matches[0]


def section_items(packet: dict[str, object], section: str) -> list[dict]:
    items = packet.get(section, [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid LLM evidence section")
    return items


def validate_packet(
    packet: EvidencePacket,
    *,
    cutoff_at: datetime,
    target_session: date,
    execution_context_id: UUID | None = None,
    knowledge_mode: str = "HISTORICAL_RECONSTRUCTION",
) -> None:
    validate_packet_data(
        packet.packet,
        instrument_id=packet.instrument_id,
        packet_hash=packet.packet_hash,
        links=packet.links,
        screening_links=packet.screening_links,
        cutoff_at=cutoff_at,
        target_session=target_session,
        execution_context_id=execution_context_id,
        knowledge_mode=knowledge_mode,
    )


def validate_packet_data(
    payload: dict[str, object],
    *,
    instrument_id: UUID,
    packet_hash: str,
    links: tuple[EvidenceLink, ...],
    cutoff_at: datetime,
    target_session: date,
    screening_links: tuple[EvidenceLink, ...] = (),
    execution_context_id: UUID | None = None,
    knowledge_mode: str = "HISTORICAL_RECONSTRUCTION",
) -> None:
    if (
        timestamp(payload.get("cutoff_at")) != timestamp(cutoff_at)
        or payload.get("target_session") != target_session.isoformat()
        or _canonical_hash(payload) != packet_hash
        or (
            execution_context_id is not None
            and payload.get("execution_context_id") != str(execution_context_id)
        )
    ):
        raise ValueError("LLM packet analysis identity/hash mismatch")
    identity = payload.get("identity")
    if not isinstance(identity, dict) or identity.get("instrument_id") != str(instrument_id):
        raise ValueError("LLM packet instrument identity mismatch")
    for link in (*links, *screening_links):
        validate_source_time(
            source_available_at=link.source_available_at,
            observed_at=link.observed_at,
            cutoff_at=cutoff_at,
            knowledge_mode=knowledge_mode,
            source_kind=link.source_kind,
        )
        if link.source_kind == "NEWS" and link.event_at is not None:
            publication_bound(link.event_at, cutoff_at)
    for link in links:
        if link.source_kind in SOURCE_SECTIONS:
            provided_item(payload, link.source_kind, link.entity_key)
        elif link.source_kind not in {"UNIVERSE", "INSTRUMENT_STATE", "DAILY_BAR"}:
            raise ValueError("Unknown LLM source kind")
    for section_name, key in SOURCE_SECTIONS.values():
        for item in section_items(payload, section_name):
            for time_key in ("published_at", "accepted_at", "source_available_at"):
                if item.get(time_key) is not None:
                    publication_bound(item[time_key], cutoff_at)
            # A future schedule known at cutoff is not a future reported result.
            if (
                section_name in {"facts", "filings"}
                and item.get("period_end") is not None
                and date.fromisoformat(str(item["period_end"]))
                > (target_session if section_name == "facts" else cutoff_at.date())
            ):
                raise ValueError("LLM packet contains a future reporting period")
            if not any(
                SOURCE_SECTIONS.get(link.source_kind) == (section_name, key)
                and link.entity_key == str(item.get(key))
                for link in links
            ):
                raise ValueError("LLM packet item has no provided source lineage")
    price = payload.get("price_context")
    if (
        isinstance(price, dict)
        and price.get("end_session") is not None
        and date.fromisoformat(str(price["end_session"])) > target_session
    ):
        raise ValueError("LLM price context exceeds analysis session")
    external_manifest = []
    for filing in section_items(payload, "filings"):
        if filing.get("external_document") is not None:
            raise ValueError("Server-acquired enrichment is no longer supported")
        if filing.get("search_evidence") is not None:
            if not isinstance(identity.get("cik"), str):
                raise ValueError("External document is missing its pinned issuer CIK")
            document_from_payload(
                filing["search_evidence"], cik=identity["cik"], filing=filing,
                cutoff_at=cutoff_at, knowledge_mode=knowledge_mode,
            )
            external_manifest.append({
                "filing_id": filing["filing_id"], "evidence": filing["search_evidence"],
            })
    if "external_enrichment_manifest_hash" in payload:
        raise ValueError("Server-acquired enrichment manifest is no longer supported")
    if (external_manifest or "llm_search_manifest_hash" in payload) and (
        payload.get("schema_version") != "4" or not external_manifest or payload.get(
            "llm_search_manifest_hash"
        ) != _canonical_hash(external_manifest)
    ):
        raise ValueError("External enrichment manifest mismatch")


def validate_model_packets(
    packets: tuple[EvidencePacket, ...], *, require_enrichment: bool = False,
) -> None:
    identities = {
        (
            packet.packet.get("cutoff_at"),
            packet.packet.get("target_session"),
            packet.packet.get("execution_context_id"),
        )
        for packet in packets
    }
    if len(identities) > 1:
        raise ValueError("LLM model input mixes analysis identities")
    for packet in packets:
        if not require_enrichment and "llm_search_manifest_hash" in packet.packet:
            raise ValueError("External scoring requires the explicitly selected enriched policy")
        if require_enrichment and (
            packet.packet.get("schema_version") != "4"
            or not packet.packet.get("llm_search_manifest_hash")
        ):
            raise ValueError("Search scoring requires admitted tool evidence and schema 4")
        validate_packet(
            packet,
            cutoff_at=timestamp(packet.packet.get("cutoff_at")),
            target_session=date.fromisoformat(str(packet.packet.get("target_session"))),
        )
