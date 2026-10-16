from __future__ import annotations

import hashlib
import multiprocessing
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services.model_artifacts import (
    ArtifactBinding,
    ModelArtifactLoader,
    ModelArtifactLoadError,
)
from sp500_candidate_engine.analytics.artifacts import ArtifactManifest


def _load_in_process(binding, cache_directory, result_queue):
    try:
        loaded = ModelArtifactLoader(Path(cache_directory)).load(binding)
        result_queue.put(("ok", str(loaded.model_path)))
    except Exception as exc:  # pragma: no cover - reported to the parent process
        result_queue.put(("error", repr(exc)))


def _artifact(tmp_path, purpose="SHORT_5D"):
    source = tmp_path / "source"
    source.mkdir()
    model = b"model weights"
    model_hash = hashlib.sha256(model).hexdigest()
    manifest = ArtifactManifest(
        schema_version=2,
        model_purpose=purpose,
        label_semantics=(
            "RAW_STOCK_5D_RETURN"
            if purpose == "SHORT_5D"
            else "RAW_STOCK_20D_RETURN"
        ),
        prediction_semantics=(
            "PREDICTED_5D_RETURN"
            if purpose == "SHORT_5D"
            else "PREDICTED_20D_RETURN"
        ),
        horizon_sessions=5 if purpose == "SHORT_5D" else 20,
        model_version_id=uuid.uuid4(),
        model_file="lightgbm.txt",
        model_sha256=model_hash,
        feature_names=("f1",),
        feature_config_hash="1" * 64,
        model_config_hash="2" * 64,
    )
    manifest_bytes = manifest.to_bytes()
    (source / "manifest.json").write_bytes(manifest_bytes)
    (source / "lightgbm.txt").write_bytes(model)
    return source, manifest_bytes, model


def test_loads_file_uri_into_hash_keyed_cache(tmp_path):
    source, manifest_bytes, _ = _artifact(tmp_path)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    binding = ArtifactBinding(
        model_purpose="SHORT_5D",
        artifact_uri=(source / "manifest.json").resolve().as_uri(),
        artifact_hash=manifest_hash,
    )

    loaded = ModelArtifactLoader(tmp_path / "cache").load(binding)

    assert loaded.manifest_path.parent.name == manifest_hash
    assert loaded.model_path.read_bytes() == b"model weights"
    assert loaded.manifest_sha256 != loaded.model_sha256


def test_file_loader_fails_closed_for_hash_and_purpose(tmp_path):
    source, manifest_bytes, _ = _artifact(tmp_path)
    loader = ModelArtifactLoader(tmp_path / "cache")
    with pytest.raises(ModelArtifactLoadError, match="Manifest SHA256"):
        loader.load(
            ArtifactBinding(
                model_purpose="SHORT_5D",
                artifact_uri=(source / "manifest.json").resolve().as_uri(),
                artifact_hash="0" * 64,
            )
        )
    with pytest.raises(ModelArtifactLoadError, match="purpose"):
        loader.load(
            ArtifactBinding(
                model_purpose="MEDIUM_20D",
                artifact_uri=(source / "manifest.json").resolve().as_uri(),
                artifact_hash=hashlib.sha256(manifest_bytes).hexdigest(),
            )
        )


def test_private_blob_validates_etag_version_and_hash(tmp_path):
    _, manifest_bytes, model = _artifact(tmp_path)
    calls = []

    def respond(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer private-token"
        if request.url.path.endswith("manifest.json"):
            return httpx.Response(
                200,
                content=manifest_bytes,
                headers={"etag": '"etag-1"', "x-ms-version-id": "version-1"},
            )
        return httpx.Response(200, content=model)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    loader = ModelArtifactLoader(
        tmp_path / "cache",
        credential=SimpleNamespace(
            get_token=lambda *_: SimpleNamespace(token="private-token")
        ),
        http_client=client,
    )
    loaded = loader.load(
        ArtifactBinding(
            model_purpose="SHORT_5D",
            artifact_uri=(
                "https://private.blob.core.windows.net/models/short/manifest.json"
            ),
            artifact_hash=hashlib.sha256(manifest_bytes).hexdigest(),
            blob_etag='"etag-1"',
            blob_version_id="version-1",
        )
    )

    assert loaded.model_path.read_bytes() == model
    assert calls[0].url.params["versionid"] == "version-1"
    assert calls[0].headers["if-match"] == '"etag-1"'
    assert calls[1].url.params.get("versionid") is None


@pytest.mark.parametrize(
    "uri",
    [
        "http://private.blob.core.windows.net/c/m.json",
        "https://example.com/c/m.json",
        "https://private.blob.core.windows.net/c/m.json?sig=public",
    ],
)
def test_rejects_nonprivate_or_non_blob_https(tmp_path, uri):
    with pytest.raises(ModelArtifactLoadError):
        ModelArtifactLoader(tmp_path / "cache").load(
            ArtifactBinding(
                model_purpose="SHORT_5D",
                artifact_uri=uri,
                artifact_hash="0" * 64,
                blob_etag='"etag"',
            )
        )


def test_cache_lock_is_multiprocess_safe(tmp_path):
    source, manifest_bytes, _ = _artifact(tmp_path)
    binding = ArtifactBinding(
        model_purpose="SHORT_5D",
        artifact_uri=(source / "manifest.json").resolve().as_uri(),
        artifact_hash=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_load_in_process,
            args=(binding, tmp_path / "cache", result_queue),
        )
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    results = [result_queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)

    assert all(process.exitcode == 0 for process in processes)
    assert all(status == "ok" for status, _ in results)
    assert len({path for _, path in results}) == 1


def test_rejects_blob_metadata_mismatch(tmp_path):
    _, manifest_bytes, _ = _artifact(tmp_path)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=manifest_bytes,
                headers={"etag": '"other"', "x-ms-version-id": "version-1"},
            )
        )
    )
    loader = ModelArtifactLoader(
        tmp_path / "cache",
        credential=SimpleNamespace(get_token=lambda *_: SimpleNamespace(token="token")),
        http_client=client,
    )
    with pytest.raises(ModelArtifactLoadError, match="ETag"):
        loader.load(
            ArtifactBinding(
                model_purpose="SHORT_5D",
                artifact_uri="https://private.blob.core.windows.net/c/manifest.json",
                artifact_hash=hashlib.sha256(manifest_bytes).hexdigest(),
                blob_etag='"expected"',
                blob_version_id="version-1",
            )
        )
