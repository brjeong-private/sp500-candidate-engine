from __future__ import annotations

import hashlib
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

import httpx
import pytest

from backend import upload_candidate_artifact as upload


def provision(tmp_path, monkeypatch, *, model_name="lightgbm.txt", checksum=None):
    root = tmp_path / "data" / "backend-artifacts" / "models"
    model = b"selected model weights"
    artifacts = {}
    for purpose in ("SHORT_5D", "MEDIUM_20D"):
        directory = root / purpose.lower()
        directory.mkdir(parents=True)
        (directory / "lightgbm.txt").write_bytes(model)
        manifest = json.dumps(
            {
                "model_purpose": purpose,
                "model_file": model_name,
                "model_sha256": checksum or hashlib.sha256(model).hexdigest(),
            }
        ).encode()
        (directory / "manifest.json").write_bytes(manifest)
        artifacts[purpose.lower()] = manifest
    monkeypatch.setattr(upload, "ROOT", tmp_path)
    return artifacts, model


@pytest.mark.parametrize("model_name", ["../other.txt", "..\\other.txt", ""])
def test_upload_rejects_nonlocal_model(tmp_path, monkeypatch, model_name):
    provision(tmp_path, monkeypatch, model_name=model_name)
    with pytest.raises(ValueError, match="must name a file"):
        upload.main()


def test_upload_rejects_corrupt_model_before_authentication(tmp_path, monkeypatch):
    provision(tmp_path, monkeypatch, checksum="0" * 64)
    with pytest.raises(ValueError, match="checksum"):
        upload.main()


@pytest.mark.parametrize("corrupt_remote_model", [False, True])
def test_upload_checks_remote_artifacts(tmp_path, monkeypatch, corrupt_remote_model):
    manifests, model = provision(tmp_path, monkeypatch)
    monkeypatch.setattr(
        upload.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout='{"accessToken":"test-token"}'),
    )
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.method == "PUT":
            with ZipFile(io.BytesIO(request.content)) as archive:
                assert set(archive.namelist()) == {
                    "short_5d/manifest.json",
                    "short_5d/lightgbm.txt",
                    "medium_20d/manifest.json",
                    "medium_20d/lightgbm.txt",
                }
            return httpx.Response(200)
        if request.url.path.endswith("manifest.json"):
            purpose = "short_5d" if "/short_5d/" in request.url.path else "medium_20d"
            return httpx.Response(200, content=manifests[purpose])
        return httpx.Response(200, content=b"corrupted" if corrupt_remote_model else model)

    client_class = httpx.Client
    monkeypatch.setattr(
        upload.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    if corrupt_remote_model:
        with pytest.raises(RuntimeError, match="Uploaded model checksum mismatch"):
            upload.main()
    else:
        upload.main()
    expected_paths = [
        "/api/zip/candidate-engine/models/",
        "/api/vfs/candidate-engine/models/short_5d/manifest.json",
        "/api/vfs/candidate-engine/models/short_5d/lightgbm.txt",
        "/api/vfs/candidate-engine/models/medium_20d/manifest.json",
        "/api/vfs/candidate-engine/models/medium_20d/lightgbm.txt",
    ]
    assert paths == (expected_paths[:3] if corrupt_remote_model else expected_paths)
