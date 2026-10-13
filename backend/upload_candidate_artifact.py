"""Upload validated model weights and manifest to App Service persistent storage."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).parents[1]


def main() -> None:
    artifacts = {}
    for purpose in ("SHORT_5D", "MEDIUM_20D"):
        directory_name = purpose.lower()
        artifact_dir = ROOT / "data" / "backend-artifacts" / "models" / directory_name
        manifest_bytes = (artifact_dir / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        if manifest.get("model_purpose") != purpose:
            raise ValueError(f"{purpose} artifact manifest purpose mismatch")
        model_name = manifest["model_file"]
        if not model_name or Path(model_name).name != model_name or "\\" in model_name:
            raise ValueError("Manifest model_file must name a file in the artifact directory")
        model_bytes = (artifact_dir / model_name).read_bytes()
        if hashlib.sha256(model_bytes).hexdigest() != manifest["model_sha256"]:
            raise ValueError("Model checksum does not match provisioned manifest")
        artifacts[directory_name] = (manifest_bytes, manifest, model_name, model_bytes)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for directory_name, artifact in artifacts.items():
            manifest_bytes, _, model_name, model_bytes = artifact
            zipped.writestr(f"{directory_name}/manifest.json", manifest_bytes)
            zipped.writestr(f"{directory_name}/{model_name}", model_bytes)
    token_response = subprocess.run(
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
    token = json.loads(token_response.stdout)["accessToken"]
    with httpx.Client(
        base_url="https://web-sp500-candidate-8d0218f4.scm.azurewebsites.net",
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    ) as client:
        response = client.put(
            "/api/zip/candidate-engine/models/",
            content=archive.getvalue(),
            headers={"Content-Type": "application/zip"},
        )
        response.raise_for_status()
        for directory_name, artifact in artifacts.items():
            manifest_bytes, manifest, model_name, _ = artifact
            saved = client.get(
                f"/api/vfs/candidate-engine/models/{directory_name}/manifest.json"
            )
            saved.raise_for_status()
            digest = hashlib.sha256(saved.content).hexdigest()
            if digest != hashlib.sha256(manifest_bytes).hexdigest():
                raise RuntimeError("Uploaded manifest checksum mismatch")
            saved_model = client.get(
                f"/api/vfs/candidate-engine/models/{directory_name}/{model_name}"
            )
            saved_model.raise_for_status()
            if hashlib.sha256(saved_model.content).hexdigest() != manifest["model_sha256"]:
                raise RuntimeError("Uploaded model checksum mismatch")
            print(f"{directory_name} model and manifest upload verified:", digest)


if __name__ == "__main__":
    main()
