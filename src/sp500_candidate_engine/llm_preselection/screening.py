from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection.config import ScreeningConfig
from sp500_candidate_engine.llm_preselection.evidence import EvidencePacket

_EVENT_KINDS = {"SEC_FILING", "SEC_FACT", "EARNINGS", "NEWS", "CORPORATE_ACTION", "EVENT"}


def _score(decision: dict[str, object]) -> int:
    value = decision["screening_event_score"]
    if type(value) is not int:
        raise TypeError("Screening score must be an integer")
    return value


@dataclass(frozen=True)
class ScreeningResult:
    packets: tuple[EvidencePacket, ...]
    audit: tuple[dict[str, object], ...]


def screen_packets(
    packets: tuple[EvidencePacket, ...],
    *,
    execution_context_id: uuid.UUID,
    cutoff_at: datetime,
    policy_version: str,
    config: ScreeningConfig,
    knowledge_mode: str = "OPERATIONAL_REPLAY",
) -> ScreeningResult:
    if cutoff_at.tzinfo is None or knowledge_mode not in {
        "OPERATIONAL_REPLAY", "HISTORICAL_RECONSTRUCTION"
    }:
        raise ValueError("Screening requires an aware cutoff and known replay mode")
    by_issuer: dict[uuid.UUID, list[EvidencePacket]] = {}
    for packet in packets:
        by_issuer.setdefault(packet.issuer_id, []).append(packet)
    decisions: list[tuple[EvidencePacket, dict[str, object], datetime]] = []
    for issuer_id, share_classes in sorted(by_issuer.items(), key=lambda item: item[0].hex):
        representative = min(share_classes, key=lambda packet: packet.instrument_id.hex)
        qualifying = {}
        for packet in share_classes:
            for link in packet.screening_links or packet.links:
                if link.source_available_at > cutoff_at or (
                    knowledge_mode == "OPERATIONAL_REPLAY" and link.source_kind in _EVENT_KINDS
                    and (link.observed_at is None or link.observed_at > cutoff_at)
                ):
                    raise ValueError("Screening evidence exceeds the point-in-time cutoff")
                recent = cutoff_at - timedelta(days=config.lookback_days) \
                    < link.source_available_at <= cutoff_at
                scheduled = (
                    link.source_kind == "EARNINGS" and link.event_at is not None
                    and cutoff_at - timedelta(days=config.earnings_window_days)
                    <= link.event_at <= cutoff_at + timedelta(days=config.earnings_window_days)
                    and link.source_available_at <= cutoff_at
                )
                if link.source_kind in _EVENT_KINDS and (recent or scheduled):
                    qualifying[(link.source_kind, link.entity_key)] = link
        kinds = {link.source_kind for link in qualifying.values()}
        # Corporate actions and other collected corporate events share one category.
        score = len(kinds - {"EVENT", "CORPORATE_ACTION"}) + bool(
            kinds & {"EVENT", "CORPORATE_ACTION"}
        )
        key = _canonical_hash({
            "execution_context_id": execution_context_id,
            "screening_policy_version": policy_version,
            "issuer_id": issuer_id,
        })
        decision: dict[str, object] = {
            "issuer_id": str(issuer_id),
            "instrument_id": str(representative.instrument_id),
            "screening_group": "EVENT" if score else "CONTROL",
            "screening_event_score": score,
            "control_sort_key": key,
            "share_class_ids": sorted(str(item.instrument_id) for item in share_classes),
            "evidence": [{
                "source_kind": link.source_kind,
                "entity_key": link.entity_key,
                "source_snapshot_id": str(link.source_snapshot_id),
                "source_available_at": link.source_available_at.isoformat(),
            } for link in sorted(
                qualifying.values(), key=lambda item: (item.source_kind, item.entity_key)
            )],
            "selected": False,
        }
        latest = max(
            (link.source_available_at for link in qualifying.values()),
            default=cutoff_at,
        )
        decisions.append((representative, decision, latest))
    events = sorted(
        (row for row in decisions if row[1]["screening_group"] == "EVENT"),
        key=lambda row: (
            -_score(row[1]),
            -row[2].timestamp(), row[0].issuer_id.hex,
        ),
    )[:config.maximum_issuers - config.control_issuers]
    controls = sorted(
        (row for row in decisions if row[1]["screening_group"] == "CONTROL"),
        key=lambda row: (str(row[1]["control_sort_key"]), row[0].issuer_id.hex),
    )[:config.control_issuers]
    selected = events + controls
    for _, decision, _ in selected:
        decision["selected"] = True
    return ScreeningResult(
        tuple(row[0] for row in selected),
        tuple(row[1] for row in decisions),
    )
