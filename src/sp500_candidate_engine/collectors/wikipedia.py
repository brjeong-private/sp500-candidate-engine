from __future__ import annotations

import hashlib
import re
from datetime import datetime

from bs4 import BeautifulSoup

from sp500_candidate_engine.http import RetryingHttpClient
from sp500_candidate_engine.models import (
    UTC,
    RunSpec,
    UniverseCollection,
    UniverseMember,
)
from sp500_candidate_engine.temporal import TemporalFence

API_URL = "https://en.wikipedia.org/w/api.php"
PAGE_TITLE = "List of S&P 500 companies"


def _clean(text: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", text).strip()


def _provider_symbol(symbol: str) -> str:
    return symbol.replace(".", "-")


class WikipediaUniverseCollector:
    def __init__(self, client: RetryingHttpClient) -> None:
        self.client = client

    async def collect(self, run_spec: RunSpec) -> UniverseCollection:
        fence = TemporalFence(run_spec)
        revision_response = await self.client.get(
            API_URL,
            params={
                "action": "query",
                "prop": "revisions",
                "titles": PAGE_TITLE,
                "rvprop": "ids|timestamp",
                "rvlimit": 10,
                "rvstart": run_spec.cutoff_at.isoformat().replace("+00:00", "Z"),
                "rvdir": "older",
                "format": "json",
                "formatversion": 2,
            },
        )
        revision_payload = revision_response.json()
        pages = revision_payload["query"]["pages"]
        revisions = pages[0].get("revisions", [])
        if not revisions:
            raise ValueError("Wikipedia returned no revision at or before the cutoff")
        selected: tuple[int, datetime, str, bytes, tuple[UniverseMember, ...]] | None = None
        rejected_revisions: list[int] = []
        for revision in revisions:
            revision_id = int(revision["revid"])
            revision_at = datetime.fromisoformat(revision["timestamp"].replace("Z", "+00:00"))
            fence.require_source_available(revision_at, field="wikipedia_revision_at")
            source_url = (
                "https://en.wikipedia.org/w/index.php"
                f"?title=List_of_S%26P_500_companies&oldid={revision_id}"
            )
            page_response = await self.client.get(source_url)
            try:
                members = self._parse_members(page_response.text)
            except ValueError:
                rejected_revisions.append(revision_id)
                continue
            selected = (
                revision_id,
                revision_at,
                source_url,
                page_response.content,
                members,
            )
            break
        if selected is None:
            raise ValueError(
                "Could not find a valid S&P 500 constituents table "
                f"in {len(revisions)} revisions at or before the cutoff"
            )
        revision_id, revision_at, source_url, page_content, members = selected
        observed_at = datetime.now(UTC)
        fence.require_observed(observed_at)
        sanitized_payload = {
            "revision_id": revision_id,
            "revision_at": revision_at.isoformat(),
            "source_url": source_url,
            "html_sha256": hashlib.sha256(page_content).hexdigest(),
            "rejected_revision_ids": rejected_revisions,
            "members": [
                {
                    "symbol": item.symbol,
                    "provider_symbol": item.provider_symbol,
                    "security_name": item.security_name,
                    "sector": item.sector,
                    "sub_industry": item.sub_industry,
                    "cik": item.cik,
                }
                for item in members
            ],
        }
        return UniverseCollection(
            revision_id=revision_id,
            revision_at=revision_at,
            source_url=source_url,
            observed_at=observed_at,
            members=members,
            sanitized_payload=sanitized_payload,
        )

    @staticmethod
    def _parse_members(html: str) -> tuple[UniverseMember, ...]:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="constituents")
        if table is None:
            raise ValueError("Could not find the S&P 500 constituents table")
        rows = table.find_all("tr")
        headers = [_clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all("th")]
        index = {name: position for position, name in enumerate(headers)}
        required = {"Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "CIK"}
        missing = required - index.keys()
        if missing:
            raise ValueError(f"Wikipedia table is missing columns: {sorted(missing)}")

        members: list[UniverseMember] = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < len(headers):
                continue
            values = [_clean(cell.get_text(" ", strip=True)) for cell in cells]
            symbol = values[index["Symbol"]]
            if not symbol:
                continue
            cik_value = values[index["CIK"]].lstrip("0") or "0"
            members.append(
                UniverseMember(
                    symbol=symbol,
                    provider_symbol=_provider_symbol(symbol),
                    security_name=values[index["Security"]],
                    sector=values[index["GICS Sector"]] or None,
                    sub_industry=values[index["GICS Sub-Industry"]] or None,
                    cik=cik_value.zfill(10),
                )
            )
        if not 490 <= len(members) <= 510:
            raise ValueError(f"Unexpected constituent count: {len(members)}")
        symbols = [member.symbol for member in members]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Duplicate symbols found in the universe revision")
        return tuple(members)
