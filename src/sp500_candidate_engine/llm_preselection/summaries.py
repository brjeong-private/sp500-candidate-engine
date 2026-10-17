from __future__ import annotations

from collections.abc import Mapping, Sequence

SUMMARY_VERSION = "scored-citations-ko-v1"
_CRITERION_LABELS = {
    "earnings": "실적", "business": "사업", "event": "이벤트",
    "financial": "재무", "industry": "산업",
}


def citation_summary(
    sub_scores: Mapping[str, object],
    citations: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> str:
    if limit < 1:
        raise ValueError("Assessment summary limit must be positive")
    reasons = []
    for citation in citations:
        criterion, reason = citation["criterion"], citation["reason"]
        if not isinstance(criterion, str) or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Invalid assessment summary citation")
        if criterion not in sub_scores or criterion not in _CRITERION_LABELS:
            raise ValueError("Unknown assessment summary criterion")
        if sub_scores[criterion] is not None:
            reasons.append(f"{_CRITERION_LABELS[criterion]}: {reason.strip()}")
    summary = " | ".join(reasons) if reasons else "근거 부족으로 평가한 항목이 없습니다."
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3] + "..." if limit > 3 else summary[:limit]
