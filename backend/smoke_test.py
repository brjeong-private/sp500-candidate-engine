"""Verify live API contracts and CORS without printing credentials or record payloads."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from dotenv import dotenv_values

from backend.app.config import PORTAL_ORIGIN

DATASETS = (
    "daily-bars",
    "corporate-actions",
    "news",
    "sec-filings",
    "sec-facts",
    "earnings",
    "universe-members",
    "exchange-sessions",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://web-sp500-candidate-8d0218f4.azurewebsites.net")
    parser.add_argument("--date", default="2026-10-09")
    parser.add_argument("--run-collection", action="store_true")
    parser.add_argument("--run-mode", choices=("DAILY", "BACKFILL"))
    parser.add_argument("--existing-run-id", type=UUID)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--expected-model-id", type=UUID)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    checks: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []

    def save_report() -> None:
        if args.output:
            args.output.write_text(
                json.dumps(
                    {
                        "verified_at": datetime.now(UTC).isoformat(),
                        "base_url": args.url,
                        "portal_origin": PORTAL_ORIGIN,
                        "collection_date": args.date,
                        "checks": checks,
                        "poll_observations": observations,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

    def check(name: str, passed: bool, **details: object) -> None:
        checks.append({"name": name, "passed": passed, **details})
        save_report()
        print(f"{'PASS' if passed else 'FAIL'} {name}")
        if not passed:
            raise AssertionError(name)

    with httpx.Client(base_url=args.url, timeout=90) as client:
        for path in ("/health/live", "/health/ready", "/openapi.json"):
            result = client.get(path, headers={"Origin": PORTAL_ORIGIN})
            check(
                path,
                result.status_code == 200
                and result.headers.get("access-control-allow-origin") == PORTAL_ORIGIN,
                status=result.status_code,
            )
        result = client.get("/api/v1/candidates", params={"date": args.date, "limit": 5})
        result.raise_for_status()
        page = result.json()
        check(
            "candidate_page", isinstance(page.get("items"), list), rows=len(page.get("items", []))
        )
        if page.get("next_cursor"):
            next_page = client.get(
                "/api/v1/candidates",
                params={"date": args.date, "limit": 5, "cursor": page["next_cursor"]},
            )
            next_page.raise_for_status()
            first_ids = {row["instrument_id"] for row in page["items"]}
            second_ids = {row["instrument_id"] for row in next_page.json()["items"]}
            check("candidate_cursor_no_duplicates", not (first_ids & second_ids))
        for dataset in DATASETS:
            result = client.get(
                f"/api/v1/collection-data/{dataset}",
                params={"start_date": args.date, "end_date": args.date, "limit": 2},
            )
            result.raise_for_status()
            page = result.json()
            check(
                dataset,
                isinstance(page.get("items"), list) and len(page["items"]) <= 2,
                rows=len(page.get("items", [])),
            )
        runs = client.get("/api/v1/pipeline-runs", params={"limit": 2})
        runs.raise_for_status()
        check("run_history", isinstance(runs.json().get("items"), list))
        preflight = client.options(
            "/api/v1/pipeline-runs",
            headers={
                "Origin": PORTAL_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            },
        )
        check(
            "portal_POST_preflight",
            preflight.status_code == 200
            and preflight.headers.get("access-control-allow-origin") == PORTAL_ORIGIN
            and "x-api-key" in preflight.headers.get("access-control-allow-headers", "").lower(),
        )
        denied = client.options(
            "/api/v1/pipeline-runs",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        check(
            "untrusted_origin_rejected",
            denied.status_code == 400 and "access-control-allow-origin" not in denied.headers,
        )
        denied = client.post("/api/v1/pipeline-runs", json={"mode": "DAILY", "date": args.date})
        check("unauthenticated_execution_rejected", denied.status_code == 401)
        invalid = client.get(
            "/api/v1/collection-data/daily-bars",
            params={"start_date": "2026-09-01", "end_date": "2026-09-11"},
        )
        check("over_ten_days_rejected", invalid.status_code == 422)
        if args.run_collection or args.run_mode or args.existing_run_id:
            key = dotenv_values(Path(__file__).parent / ".env").get("BACKEND_API_KEY")
            if not key:
                raise ValueError("Local backend/.env must contain BACKEND_API_KEY")
            invalid = client.post(
                "/api/v1/pipeline-runs",
                headers={"X-API-Key": key},
                json={"mode": "DAILY", "date": "2099-01-01", "with_candidates": True},
            )
            check("authenticated_future_date_rejected", invalid.status_code == 422)
            mode = args.run_mode or "RANGE"
            payload = (
                {"mode": "DAILY", "date": args.date, "with_candidates": True}
                if mode == "DAILY"
                else {
                    "mode": mode,
                    "start_date": args.date,
                    "end_date": args.date,
                    **({"with_candidates": False} if mode == "RANGE" else {}),
                }
            )
            if args.existing_run_id:
                run_id = str(args.existing_run_id)
            else:
                started = client.post(
                    "/api/v1/pipeline-runs",
                    headers={"X-API-Key": key},
                    json=payload,
                )
                check("authenticated_execution_accepted", started.status_code == 202)
                run_id = started.json()["process_run_id"]
            print(f"Verifying {mode} run {run_id}")
            deadline = time.monotonic() + args.timeout_seconds
            gateway_errors = 0
            while time.monotonic() < deadline:
                status_response = client.get(f"/api/v1/pipeline-runs/{run_id}")
                observations.append(
                    {
                        "at": datetime.now(UTC).isoformat(),
                        "run_id": run_id,
                        "http_status": status_response.status_code,
                        "elapsed_seconds": status_response.elapsed.total_seconds(),
                        "request_id": status_response.headers.get("X-Request-ID"),
                        "server": status_response.headers.get("Server"),
                    }
                )
                save_report()
                if status_response.status_code in {502, 503, 504}:
                    gateway_errors += 1
                    print(f"RETRY status gateway HTTP {status_response.status_code}")
                    if gateway_errors >= 5:
                        status_response.raise_for_status()
                    time.sleep(5)
                    continue
                status_response.raise_for_status()
                gateway_errors = 0
                progress = status_response.json()
                status = progress["status"]
                if status not in {"PENDING", "RUNNING"}:
                    check(
                        "execution_completed", status == "SUCCEEDED", status=status, run_id=run_id
                    )
                    break
                time.sleep(5)
            else:
                raise TimeoutError(
                    f"Accepted pipeline did not finish within {args.timeout_seconds} seconds"
                )
            details = client.get(f"/api/v1/pipeline-runs/{run_id}/dates")
            details.raise_for_status()
            check("execution_date_details", isinstance(details.json().get("items"), list))
            if mode == "DAILY":
                candidates = client.get(
                    "/api/v1/candidates",
                    params={"date": args.date, "limit": 20},
                )
                candidates.raise_for_status()
                items = candidates.json()["items"]
                check("daily_candidate_count", 5 <= len(items) <= 10, rows=len(items))
                if args.expected_model_id:
                    check(
                        "daily_pinned_model",
                        all(
                            item["model_version_id"] == str(args.expected_model_id)
                            for item in items
                        ),
                    )
    save_report()


if __name__ == "__main__":
    main()
