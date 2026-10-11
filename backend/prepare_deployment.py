"""Create a source-only App Service ZIP and secure, ignored Bicep parameters."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import zipfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output = ROOT / ".azure"
    backend_env = ROOT / "backend" / ".env"
    if not backend_env.exists():
        backend_env.write_text(f"BACKEND_API_KEY={secrets.token_urlsafe(48)}\n", encoding="utf-8")
    values = {**dotenv_values(ROOT / ".env"), **dotenv_values(backend_env), **os.environ}
    required = (
        "PGHOST",
        "PGDATABASE",
        "MASSIVE_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "BACKEND_API_KEY",
        "HTTP_USER_AGENT",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError("Missing deployment settings: " + ", ".join(missing))
    parameters = {
        "location": "koreacentral",
        "postgresHost": values["PGHOST"],
        "postgresDatabase": values["PGDATABASE"],
        "httpUserAgent": values["HTTP_USER_AGENT"],
        "candidateManifestSha256": hashlib.sha256(
            (ROOT / "data" / "backend-artifacts" / "models" / "manifest.json").read_bytes()
        ).hexdigest(),
        "apiKey": values["BACKEND_API_KEY"],
        "massiveApiKey": values["MASSIVE_API_KEY"],
        "alphaVantageApiKey": values["ALPHA_VANTAGE_API_KEY"],
    }
    parameter_path = output / "backend.parameters.tmp.json"
    parameter_path.write_text(
        json.dumps(
            {
                "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {key: {"value": value} for key, value in parameters.items()},
            }
        ),
        encoding="utf-8",
    )
    archive_path = output / "backend-source.tmp.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("backend", "src", "config", "sql"):
            for path in sorted((ROOT / directory).rglob("*")):
                if (
                    not path.is_file()
                    or "__pycache__" in path.parts
                    or path.name.startswith(".env")
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    continue
                archive.write(path, path.relative_to(ROOT).as_posix())
        for name in ("pyproject.toml", "README.md"):
            archive.write(ROOT / name, name)
        archive.write(ROOT / "backend" / "requirements.txt", "requirements.txt")
    print(f"Prepared source ZIP: {archive_path}")
    print(
        "Parameters contain secrets; use --output none and remove the parameter file after deploy."
    )


if __name__ == "__main__":
    main()
