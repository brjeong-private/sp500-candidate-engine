from __future__ import annotations

import json
import re
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Literal
from urllib.parse import unquote, urlsplit

from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection.asof import NEW_YORK, llm_cutoff, publication_bound

ENRICHMENT_VERSION = "llm-search-evidence-v3"
SEARCH_OMISSION_VERSION = "llm-search-omission-v1"
SEARCH_OMISSION_GAP = "검증을 통과한 외부 검색 자료가 없어 DB 자료만으로 평가했습니다."
_HASH = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ExternalFact:
    kind: str
    name: str
    value: str
    period_end: str | None


@dataclass(frozen=True)
class VerifiedSearchEvidence:
    schema_version: str
    accession_no: str
    cik: str
    source_url: str
    parent_accepted_at: str
    source_available_at: str
    source_local_date: str
    source_date_precision: Literal["DAY", "TIMESTAMP"]
    retrieved_at: str
    model_snapshot: str | None
    tool_response_hash: str
    evidence_hash: str
    artifact_key: str
    facts: tuple[ExternalFact, ...]

    def payload(self) -> dict[str, object]:
        return json.loads(json.dumps(asdict(self)))


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Search evidence requires an explicit timestamp")
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Search evidence timestamp must be timezone-aware")
    return result


def source_filing(url: str, cik: str, filings: list[dict], cutoff_at: datetime) -> dict:
    """Use frozen publication metadata, never a date asserted by the search model."""
    parsed = urlsplit(url)
    path = unquote(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.sec.gov", "sec.gov"}
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or "\\" in path
        or "/../" in path
    ):
        raise ValueError("SEARCH_SOURCE_NOT_FROZEN")
    if not re.fullmatch(r"\d{1,10}", cik):
        raise ValueError("Search evidence has no pinned issuer CIK")
    for filing in filings:
        accession = filing.get("accession_no")
        if not isinstance(accession, str) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            raise ValueError("Malformed pinned accession")
        base = f"/Archives/edgar/data/{int(cik)}/"
        root_original = base + accession + ".txt"
        bundle = base + accession.replace("-", "") + "/"
        leaf = path[len(bundle) :] if path.startswith(bundle) else ""
        original_leaf = bool(re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:htm|html|txt|pdf)", leaf))
        if path == root_original or (
            original_leaf and not leaf.lower().startswith("index") and "-index." not in leaf.lower()
        ):
            publication_bound(filing["accepted_at"], cutoff_at)
            return filing
    raise ValueError("SEARCH_SOURCE_NOT_FROZEN")


def _future_text(value: str, cutoff: datetime) -> bool:
    for match in re.finditer(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", value):
        if date(*map(int, match.groups())) > cutoff.date():
            return True
    for match in re.finditer(r"(20\d{2})년\s*(\d{1,2})월\s*(\d{1,2})일", value):
        if date(*map(int, match.groups())) > cutoff.date():
            return True
    for match in re.finditer(r"(20\d{2})년?\s*([1-4])분기", value):
        year, quarter = map(int, match.groups())
        month = quarter * 3
        if date(year, month, monthrange(year, month)[1]) > cutoff.date():
            return True
    for match in re.finditer(r"\bQ([1-4])\s*(20\d{2})\b", value, re.I):
        quarter, year = map(int, match.groups())
        month = quarter * 3
        if date(year, month, monthrange(year, month)[1]) > cutoff.date():
            return True
    return any(int(year) > cutoff.year for year in re.findall(r"(?<!\d)(20\d{2})(?!\d)", value))


def evidence_hash(evidence: VerifiedSearchEvidence) -> str:
    payload = evidence.payload()
    payload.pop("evidence_hash")
    return _canonical_hash(payload)


PERIOD_ENRICHMENT_VERSION = "llm-period-evidence-v1"
_FACT_LABEL = re.compile(r"(20\d{2}-\d{2}-\d{2})(?: (\d{2}):(\d{2}))? \| ")


def _label_allowed(label: re.Match[str], cutoff_at: datetime) -> bool:
    """Replay the New York day rule on the Python-written fact label."""
    cutoff_local = cutoff_at.astimezone(NEW_YORK)
    day = date.fromisoformat(label[1])
    if day < cutoff_local.date():
        return label[2] is None
    if day > cutoff_local.date() or label[2] is None:
        return False
    stamp = datetime(day.year, day.month, day.day, int(label[2]), int(label[3]), tzinfo=NEW_YORK)
    return stamp < cutoff_at


def _period_evidence(
    raw: dict,
    *,
    filings: list[dict],
    cik: str,
    cutoff_at: datetime,
    observed_at: datetime,
    model_snapshot: str | None,
    artifact_key: str,
    max_facts: int,
    source_pages: dict[str, dict] | None,
) -> list[tuple[str, VerifiedSearchEvidence]]:
    """Admit period-search passages by the Python-read date of each cited page."""
    if not filings or not source_pages:
        raise ValueError("PERIOD_SEARCH_SOURCE_DATES_MISSING")
    anchor = max(filings, key=lambda item: str(item["accepted_at"]))
    facts: list[ExternalFact] = []
    urls: list[str] = []
    precisions: set[str] = set()
    for message in raw["output"]:
        if message.get("type") != "message" or not isinstance(message.get("content"), list):
            continue
        for content in message["content"]:
            text, annotations = content.get("text"), content.get("annotations")
            if content.get("type") != "output_text" or not isinstance(text, str):
                continue
            if not isinstance(annotations, list):
                raise ValueError("SEARCH_CITATIONS_MISSING")
            for annotation in annotations:
                if annotation.get("type") != "url_citation" or not isinstance(
                    annotation.get("url"), str
                ):
                    continue
                url = annotation["url"].split("#", 1)[0]
                start, end = annotation.get("start_index"), annotation.get("end_index")
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(
                    text
                ):
                    raise ValueError("SEARCH_CITATION_OFFSETS_INVALID")
                ledger = source_pages.get(url)
                if not isinstance(ledger, dict) or ledger.get("status") != "ADMITTED":
                    continue
                left = text.rfind("\n", 0, start) + 1
                right = text.find("\n", end)
                passage = text[left : right if right >= 0 else len(text)]
                same = [
                    a for a in annotations
                    if a.get("type") == "url_citation" and isinstance(a.get("url"), str)
                    and type(a.get("start_index")) is int and type(a.get("end_index")) is int
                    and left <= a["start_index"] < a["end_index"] <= (
                        right if right >= 0 else len(text)
                    )
                ]
                if any(a["url"].split("#", 1)[0] != url for a in same):
                    continue
                for cited in same:
                    passage = passage.replace(text[cited["start_index"] : cited["end_index"]], "")
                passage = re.sub(
                    r"^\s*20\d{2}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?\s*[|:]\s*", "", passage
                )
                passage = passage.strip()
                if (
                    not passage
                    or _future_text(passage, cutoff_at)
                    or re.search(
                        r"확인\s*불가|cannot\s+(?:verify|retrieve)|unable\s+to", passage, re.I
                    )
                ):
                    continue
                value = f"{ledger['label']} | {passage[:380]} (출처: {url[:180]})"
                fact = ExternalFact("LLM_GROUNDED_EXTRACT", "SEARCH:CITED_PASSAGE", value, None)
                if fact not in facts:
                    facts.append(fact)
                    precisions.add(str(ledger["precision"]))
                    if url not in urls:
                        urls.append(url)
    if not facts or len(facts) > max_facts:
        raise ValueError("SEARCH_HAS_NO_BOUNDED_ADMISSIBLE_FACTS")
    labels = [_FACT_LABEL.match(fact.value) for fact in facts]
    if any(label is None or not _label_allowed(label, cutoff_at) for label in labels):
        raise ValueError("SEARCH_PASSAGE_TIME_OR_BOUNDS_INVALID")
    newest = max(str(label[1]) for label in labels if label is not None)
    evidence = VerifiedSearchEvidence(
        PERIOD_ENRICHMENT_VERSION,
        anchor["accession_no"],
        cik.zfill(10),
        urls[0],
        str(anchor["accepted_at"]),
        cutoff_at.isoformat(),
        newest,
        "TIMESTAMP" if "TIMESTAMP" in precisions else "DAY",
        observed_at.isoformat(),
        model_snapshot,
        _canonical_hash(raw),
        "",
        artifact_key,
        tuple(facts),
    )
    evidence = VerifiedSearchEvidence(
        **{**asdict(evidence), "facts": evidence.facts, "evidence_hash": evidence_hash(evidence)}
    )
    return [(str(anchor["filing_id"]), evidence)]


def validate_search_response(
    raw: dict,
    *,
    cik: str,
    filings: list[dict],
    cutoff_at: datetime,
    observed_at: datetime,
    knowledge_mode: str,
    artifact_key: str,
    max_tool_calls: int,
    max_facts: int,
    provider: str = "AZURE_OPENAI_WEB_SEARCH",
    source_pages: dict[str, dict] | None = None,
) -> list[tuple[str, VerifiedSearchEvidence]]:
    cutoff_at = llm_cutoff(cutoff_at)
    if (
        raw.get("status") != "completed"
        or raw.get("error") is not None
        or raw.get("previous_response_id") is not None
        or knowledge_mode not in {"OPERATIONAL_REPLAY", "HISTORICAL_RECONSTRUCTION"}
        or (knowledge_mode == "OPERATIONAL_REPLAY" and observed_at > cutoff_at)
    ):
        raise ValueError("SEARCH_RESPONSE_OR_OBSERVATION_INVALID")
    model_snapshot = raw.get("model") if isinstance(raw.get("model"), str) else None
    output = raw.get("output")
    if not isinstance(output, list) or any(not isinstance(item, dict) for item in output):
        raise ValueError("SEARCH_TOOL_TRACE_MISSING")
    if provider == "AZURE_BING_GROUNDING_PERIOD":
        calls = [item for item in output if item.get("type") == "bing_grounding_call"]
        returns = [item for item in output if item.get("type") == "bing_grounding_call_output"]
        if not 1 <= len(calls) <= max_tool_calls or any(
            call.get("status") != "completed" for call in calls
        ):
            raise ValueError("PERIOD_SEARCH_TOOL_TRACE_INVALID")
        for call in calls:
            matched = [item for item in returns if item.get("call_id") == call.get("call_id")]
            if len(matched) != 1 or matched[0].get("status") != "completed":
                raise ValueError("PERIOD_SEARCH_TOOL_OUTPUT_MISSING")
        return _period_evidence(
            raw,
            filings=filings,
            cik=cik,
            cutoff_at=cutoff_at,
            observed_at=observed_at,
            model_snapshot=model_snapshot,
            artifact_key=artifact_key,
            max_facts=max_facts,
            source_pages=source_pages,
        )
    if any(item.get("type") not in {"web_search_call", "message", "reasoning"} for item in output):
        raise ValueError("SEARCH_UNEXPECTED_TOOL_OR_CONTEXT")
    calls = [item for item in output if item.get("type") == "web_search_call"]
    if not 1 <= len(calls) <= max_tool_calls:
        raise ValueError("SEARCH_TOOL_TRACE_MISSING_OR_OVER_BUDGET")
    observed_urls = set()
    for call in calls:
        action = call.get("action")
        if call.get("status") != "completed" or not isinstance(action, dict):
            raise ValueError("SEARCH_TOOL_DID_NOT_COMPLETE")
        if action.get("type") == "search":
            queries = action.get("queries", [action.get("query", "")])
            if not isinstance(queries, list) or any(
                not isinstance(query, str) or _future_text(query, cutoff_at) for query in queries
            ):
                raise ValueError("SEARCH_QUERY_USES_FUTURE_PERIOD")
            sources = action.get("sources")
            if not isinstance(sources, list) or not sources:
                raise ValueError("SEARCH_ALL_SOURCES_MISSING")
            for source in sources:
                if (
                    not isinstance(source, dict)
                    or source.get("type") != "url"
                    or not isinstance(source.get("url"), str)
                ):
                    raise ValueError("SEARCH_SOURCE_MALFORMED")
                if source.get("published_at") is not None:
                    publication_bound(source["published_at"], cutoff_at)
                observed_urls.add(source["url"].split("#", 1)[0])
        elif action.get("type") in {"open_page", "find_in_page"}:
            if not isinstance(action.get("url"), str):
                raise ValueError("SEARCH_SOURCE_MALFORMED")
            observed_urls.add(action["url"].split("#", 1)[0])
        else:
            raise ValueError("SEARCH_ACTION_NOT_SUPPORTED")
    # Reject the entire search if any consulted source is unsafe, not just its visible citations.
    for url in observed_urls:
        source_filing(url, cik, filings, cutoff_at)
    passages: dict[str, list[ExternalFact]] = {}
    used_urls = {}
    for message in output:
        if message.get("type") != "message":
            continue
        contents = message.get("content")
        if not isinstance(contents, list) or any(not isinstance(item, dict) for item in contents):
            raise ValueError("SEARCH_MESSAGE_MALFORMED")
        for content in contents:
            if content.get("type") != "output_text":
                continue
            text, annotations = content.get("text"), content.get("annotations")
            if (
                not isinstance(text, str)
                or not isinstance(annotations, list)
                or any(not isinstance(item, dict) for item in annotations)
            ):
                raise ValueError("SEARCH_CITATIONS_MISSING")
            if _future_text(text, cutoff_at):
                raise ValueError("SEARCH_RESPONSE_CONTAINS_FUTURE_TEXT")
            for annotation in annotations:
                if annotation.get("type") != "url_citation":
                    continue
                url = annotation.get("url")
                if isinstance(url, str):
                    url = url.split("#", 1)[0]
                if url not in observed_urls:
                    raise ValueError("SEARCH_CITATION_NOT_IN_TOOL_SOURCES")
                filing = source_filing(url, cik, filings, cutoff_at)
                start, end = annotation.get("start_index"), annotation.get("end_index")
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 0 <= start < end <= len(text)
                ):
                    raise ValueError("SEARCH_CITATION_OFFSETS_INVALID")
                left = text.rfind("\n", 0, start) + 1
                right = text.find("\n", end)
                passage = text[left : right if right >= 0 else len(text)]
                for cited in annotations:
                    if cited.get("type") == "url_citation":
                        a, b = cited.get("start_index"), cited.get("end_index")
                        if (
                            type(a) is int
                            and type(b) is int
                            and left <= a < b <= (right if right >= 0 else len(text))
                        ):
                            if (
                                source_filing(cited["url"], cik, filings, cutoff_at)["filing_id"]
                                != filing["filing_id"]
                            ):
                                raise ValueError("SEARCH_PARAGRAPH_MIXES_ORIGINAL_VERSIONS")
                            passage = passage.replace(text[a:b], "")
                passage = passage.strip()
                if re.search(
                    r"확인\s*불가|본문.{0,30}(?:못|않)|cannot\s+(?:verify|retrieve)|"
                    r"unable\s+to|not\s+(?:retrieved|available)",
                    passage,
                    re.I,
                ):
                    continue
                first_date = re.match(r"(20\d{2}-\d{2}-\d{2})\s*[|:]", passage)
                bound = publication_bound(filing["accepted_at"], cutoff_at)
                if (
                    first_date is None
                    or first_date[1] != bound.local_date.isoformat()
                    or _future_text(passage, bound.upper_bound_at.astimezone(NEW_YORK))
                    or not 1 <= len(passage) <= 600
                ):
                    raise ValueError("SEARCH_PASSAGE_TIME_OR_BOUNDS_INVALID")
                key = str(filing["filing_id"])
                facts = passages.setdefault(key, [])
                fact = ExternalFact("LLM_GROUNDED_EXTRACT", "SEARCH:CITED_PASSAGE", passage, None)
                if fact not in facts:
                    facts.append(fact)
                used_urls[key] = url
    if not passages or sum(map(len, passages.values())) > max_facts:
        raise ValueError("SEARCH_HAS_NO_BOUNDED_ADMISSIBLE_FACTS")
    results = []
    for key, facts in passages.items():
        filing = next(item for item in filings if str(item["filing_id"]) == key)
        bound = publication_bound(filing["accepted_at"], cutoff_at)
        evidence = VerifiedSearchEvidence(
            ENRICHMENT_VERSION,
            filing["accession_no"],
            cik.zfill(10),
            used_urls[key],
            str(filing["accepted_at"]),
            bound.upper_bound_at.isoformat(),
            bound.local_date.isoformat(),
            bound.precision,
            observed_at.isoformat(),
            model_snapshot,
            _canonical_hash(raw),
            "",
            artifact_key,
            tuple(facts),
        )
        evidence = VerifiedSearchEvidence(
            **{
                **asdict(evidence),
                "facts": evidence.facts,
                "evidence_hash": evidence_hash(evidence),
            }
        )
        results.append((key, evidence))
    return results


def document_from_payload(
    value: object,
    *,
    cik: str,
    filing: dict,
    cutoff_at: datetime,
    knowledge_mode: str,
) -> VerifiedSearchEvidence:
    if not isinstance(value, dict):
        raise ValueError("Search evidence must be an object")
    fields = set(VerifiedSearchEvidence.__dataclass_fields__) - {"facts"}
    if (
        set(value) != fields | {"facts"}
        or any(not isinstance(value[key], str) for key in fields - {"model_snapshot"})
        or (
            value.get("model_snapshot") is not None and not isinstance(value["model_snapshot"], str)
        )
        or not isinstance(value["facts"], list)
        or not 1 <= len(value["facts"]) <= 20
    ):
        raise ValueError("Search evidence fields are invalid")
    period = value.get("schema_version") == PERIOD_ENRICHMENT_VERSION
    facts = []
    for fact in value["facts"]:
        if (
            not isinstance(fact, dict)
            or set(fact) != {"kind", "name", "value", "period_end"}
            or fact["kind"] != "LLM_GROUNDED_EXTRACT"
            or fact["name"] != "SEARCH:CITED_PASSAGE"
            or not isinstance(fact["value"], str)
            or not 1 <= len(fact["value"]) <= 600
            or fact["period_end"] is not None
            or (
                not period
                and _future_text(
                    fact["value"],
                    publication_bound(
                        filing["accepted_at"], cutoff_at
                    ).upper_bound_at.astimezone(NEW_YORK),
                )
            )
        ):
            raise ValueError("Search evidence passage is invalid")
        facts.append(ExternalFact(**fact))
    result = VerifiedSearchEvidence(
        **{key: value[key] for key in fields},
        facts=tuple(facts),
    )
    if period:
        effective = llm_cutoff(cutoff_at)
        labels = [_FACT_LABEL.match(fact.value) for fact in facts]
        if (
            int(result.cik) != int(cik)
            or result.accession_no != filing["accession_no"]
            or result.parent_accepted_at != str(filing["accepted_at"])
            or timestamp(result.source_available_at) != effective
            or urlsplit(result.source_url).scheme != "https"
            or not _HASH.fullmatch(result.tool_response_hash)
            or not re.fullmatch(r"[0-9a-f]{64}\.json", result.artifact_key)
            or result.evidence_hash != evidence_hash(result)
            or any(label is None or not _label_allowed(label, effective) for label in labels)
            or result.source_local_date != max(
                label[1] for label in labels if label is not None
            )
            or result.source_date_precision != (
                "TIMESTAMP"
                if result.source_local_date == effective.astimezone(NEW_YORK).date().isoformat()
                else "DAY"
            )
            or knowledge_mode not in {"HISTORICAL_RECONSTRUCTION", "OPERATIONAL_REPLAY"}
            or (
                knowledge_mode == "OPERATIONAL_REPLAY"
                and timestamp(result.retrieved_at) > effective
            )
        ):
            raise ValueError("Search evidence publication/provenance mismatch")
        return result
    parent = source_filing(result.source_url, cik, [filing], cutoff_at)
    bound = publication_bound(parent["accepted_at"], cutoff_at)
    if (
        result.schema_version != ENRICHMENT_VERSION
        or int(result.cik) != int(cik)
        or result.accession_no != parent["accession_no"]
        or timestamp(result.source_available_at) != bound.upper_bound_at
        or result.source_local_date != bound.local_date.isoformat()
        or result.source_date_precision != bound.precision
        or result.parent_accepted_at != str(parent["accepted_at"])
        or not _HASH.fullmatch(result.tool_response_hash)
        or not re.fullmatch(r"[0-9a-f]{64}\.json", result.artifact_key)
        or result.evidence_hash != evidence_hash(result)
        or knowledge_mode not in {"HISTORICAL_RECONSTRUCTION", "OPERATIONAL_REPLAY"}
        or (knowledge_mode == "OPERATIONAL_REPLAY" and timestamp(result.retrieved_at) > cutoff_at)
    ):
        raise ValueError("Search evidence publication/provenance mismatch")
    return result
