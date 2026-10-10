import asyncio
from datetime import date

import httpx

from sp500_candidate_engine.collectors.wikipedia import WikipediaUniverseCollector
from sp500_candidate_engine.models import KnowledgeMode, RunSpec


def _constituents_html(count: int = 490) -> str:
    rows = "".join(
        (
            "<tr>"
            f"<td>S{index:03d}</td>"
            f"<td>Security {index}</td>"
            "<td>Sector</td>"
            "<td>Industry</td>"
            f"<td>{index + 1:010d}</td>"
            "</tr>"
        )
        for index in range(count)
    )
    return (
        '<table id="constituents">'
        "<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>"
        "<th>GICS Sub-Industry</th><th>CIK</th></tr>"
        f"{rows}</table>"
    )


class FakeWikipediaClient:
    def __init__(self) -> None:
        self.page_requests: list[str] = []

    async def get(
        self,
        url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        if params is not None:
            assert params["rvlimit"] == 10
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "revisions": [
                                    {"revid": 2, "timestamp": "2025-11-24T20:00:00Z"},
                                    {"revid": 1, "timestamp": "2025-11-24T19:00:00Z"},
                                ]
                            }
                        ]
                    }
                },
                request=httpx.Request("GET", url),
            )
        self.page_requests.append(url)
        html = "<html>missing table</html>" if "oldid=2" in url else _constituents_html()
        return httpx.Response(
            200,
            text=html,
            request=httpx.Request("GET", url),
        )


def test_wikipedia_uses_older_valid_revision_before_cutoff() -> None:
    client = FakeWikipediaClient()
    collector = WikipediaUniverseCollector(client)  # type: ignore[arg-type]
    run_spec = RunSpec.for_date(
        date(2025, 11, 24),
        KnowledgeMode.HISTORICAL_RECONSTRUCTION,
    )

    result = asyncio.run(collector.collect(run_spec))

    assert result.revision_id == 1
    assert len(result.members) == 490
    assert result.sanitized_payload["rejected_revision_ids"] == [2]
    assert [url.rsplit("=", 1)[-1] for url in client.page_requests] == ["2", "1"]
