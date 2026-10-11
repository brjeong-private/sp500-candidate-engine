"""Print compact Kudu deployment status using Azure CLI Entra authentication."""

from __future__ import annotations

import argparse
import json
import subprocess

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logs", action="store_true")
    args = parser.parse_args()
    output = subprocess.run(
        [
            "az.cmd",
            "account",
            "get-access-token",
            "--resource",
            "https://management.azure.com/",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    token = json.loads(output.stdout)["accessToken"]
    with httpx.Client(
        base_url="https://web-sp500-candidate-8d0218f4.scm.azurewebsites.net",
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,
    ) as client:
        response = client.get("/api/deployments/latest")
        response.raise_for_status()
        deployment = response.json()
        print(
            json.dumps(
                {
                    key: deployment.get(key)
                    for key in (
                        "id",
                        "status",
                        "status_text",
                        "complete",
                        "active",
                        "start_time",
                        "end_time",
                    )
                }
            )
        )
        if args.logs:
            logs = client.get(f"/api/deployments/{deployment['id']}/log")
            logs.raise_for_status()
            for entry in logs.json()[-5:]:
                print(entry["message"])
                if entry.get("details_url"):
                    detail = client.get(entry["details_url"])
                    detail.raise_for_status()
                    for message in detail.json()[-12:]:
                        print(message["message"])


if __name__ == "__main__":
    main()
