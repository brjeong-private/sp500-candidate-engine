from __future__ import annotations

import email.utils
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse
from urllib.request import url2pathname

import httpx
from azure.identity import DefaultAzureCredential

from sp500_candidate_engine.analytics.artifacts import (
    MODEL_PURPOSES,
    ArtifactManifest,
    ArtifactValidationError,
    sha256_bytes,
    sha256_file,
)

AZURE_STORAGE_SCOPE = "https://storage.azure.com/.default"
AZURE_STORAGE_API_VERSION = "2023-11-03"


class TokenCredential(Protocol):
    def get_token(self, *scopes: str): ...


@dataclass(frozen=True)
class ArtifactBinding:
    model_purpose: str
    artifact_uri: str
    artifact_hash: str
    blob_etag: str | None = None
    blob_version_id: str | None = None


@dataclass(frozen=True)
class MaterializedModelArtifact:
    manifest: ArtifactManifest
    manifest_path: Path
    model_path: Path
    manifest_sha256: str
    model_sha256: str


class ModelArtifactLoadError(RuntimeError):
    pass


def _valid_sha256(value: str) -> bool:
    return (
        len(value) == 64
        and value.lower() == value
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_binding(binding: ArtifactBinding) -> None:
    if binding.model_purpose not in MODEL_PURPOSES:
        raise ModelArtifactLoadError(
            f"Unsupported model purpose: {binding.model_purpose}"
        )
    if not _valid_sha256(binding.artifact_hash):
        raise ModelArtifactLoadError("Manifest artifact_hash must be a lowercase SHA256")
    parsed = urlparse(binding.artifact_uri)
    if parsed.scheme == "file":
        if parsed.query or parsed.fragment:
            raise ModelArtifactLoadError("file artifact URI cannot have query or fragment")
        if binding.blob_etag is not None or binding.blob_version_id is not None:
            raise ModelArtifactLoadError("file artifact URI cannot have Blob metadata")
        return
    if parsed.scheme != "https":
        raise ModelArtifactLoadError("Artifact URI must use private Azure Blob HTTPS or file")
    if (
        parsed.username
        or parsed.password
        or parsed.port
        or not parsed.hostname
        or not parsed.hostname.lower().endswith(".blob.core.windows.net")
    ):
        raise ModelArtifactLoadError("HTTPS artifact URI must target Azure Blob Storage")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) - {"versionid"} or "sig" in query:
        raise ModelArtifactLoadError("Public or unrecognized Blob URI query is not allowed")
    uri_version = query.get("versionid", ())
    if len(uri_version) > 1:
        raise ModelArtifactLoadError("Blob URI has multiple version IDs")
    if uri_version and binding.blob_version_id is None:
        raise ModelArtifactLoadError("Blob URI version must be pinned by the assignment")
    if binding.blob_version_id and uri_version and uri_version[0] != binding.blob_version_id:
        raise ModelArtifactLoadError("Blob URI version does not match assignment")
    if binding.blob_etag is None and binding.blob_version_id is None:
        raise ModelArtifactLoadError("Blob assignment requires ETag or version ID")


def _file_uri_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.netloc not in ("", "localhost"):
        raise ModelArtifactLoadError("file artifact URI must be local")
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc == "" and len(path) >= 3 and path[0] in ("/", "\\") and path[2] == ":":
        path = path[1:]
    return Path(path)


def _model_blob_uri(manifest_uri: str, model_file: str) -> str:
    parsed = urlparse(manifest_uri)
    path = parsed.path.rsplit("/", 1)[0] + "/" + quote(model_file, safe="")
    return urlunparse(parsed._replace(path=path, query=""))


@contextmanager
def _process_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        if locked and os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        elif locked:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class ModelArtifactLoader:
    def __init__(
        self,
        cache_directory: Path,
        *,
        credential: TokenCredential | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.cache_directory = Path(cache_directory)
        self.credential = credential
        self.http_client = http_client

    def load(self, binding: ArtifactBinding) -> MaterializedModelArtifact:
        _validate_binding(binding)
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        destination = self.cache_directory / binding.artifact_hash
        lock_path = self.cache_directory / f".{binding.artifact_hash}.lock"
        with _process_lock(lock_path):
            cached = self._read_cached(destination, binding)
            if cached is not None:
                return cached
            if destination.exists():
                shutil.rmtree(destination)
            temporary = self.cache_directory / (
                f".{binding.artifact_hash}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            )
            temporary.mkdir()
            try:
                manifest_bytes, model_bytes = self._download(binding)
                if sha256_bytes(manifest_bytes) != binding.artifact_hash:
                    raise ModelArtifactLoadError("Manifest SHA256 does not match assignment")
                try:
                    manifest = ArtifactManifest.from_bytes(
                        manifest_bytes, expected_purpose=binding.model_purpose
                    )
                except ArtifactValidationError as exc:
                    raise ModelArtifactLoadError(str(exc)) from exc
                if sha256_bytes(model_bytes) != manifest.model_sha256:
                    raise ModelArtifactLoadError("Model weight SHA256 does not match manifest")
                (temporary / "manifest.json").write_bytes(manifest_bytes)
                (temporary / manifest.model_file).write_bytes(model_bytes)
                try:
                    os.replace(temporary, destination)
                except FileExistsError:
                    shutil.rmtree(temporary)
                loaded = self._read_cached(destination, binding)
                if loaded is None:
                    raise ModelArtifactLoadError("Materialized artifact failed cache validation")
                return loaded
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

    def _read_cached(
        self,
        destination: Path,
        binding: ArtifactBinding,
    ) -> MaterializedModelArtifact | None:
        manifest_path = destination / "manifest.json"
        if not manifest_path.is_file():
            return None
        manifest_bytes = manifest_path.read_bytes()
        if sha256_bytes(manifest_bytes) != binding.artifact_hash:
            return None
        try:
            manifest = ArtifactManifest.from_bytes(
                manifest_bytes, expected_purpose=binding.model_purpose
            )
        except ArtifactValidationError:
            return None
        model_path = destination / manifest.model_file
        if not model_path.is_file() or sha256_file(model_path) != manifest.model_sha256:
            return None
        return MaterializedModelArtifact(
            manifest=manifest,
            manifest_path=manifest_path,
            model_path=model_path,
            manifest_sha256=binding.artifact_hash,
            model_sha256=manifest.model_sha256,
        )

    def _download(self, binding: ArtifactBinding) -> tuple[bytes, bytes]:
        parsed = urlparse(binding.artifact_uri)
        if parsed.scheme == "file":
            manifest_path = _file_uri_path(binding.artifact_uri)
            try:
                manifest_bytes = manifest_path.read_bytes()
                manifest = ArtifactManifest.from_bytes(
                    manifest_bytes, expected_purpose=binding.model_purpose
                )
                model_bytes = (manifest_path.parent / manifest.model_file).read_bytes()
            except ArtifactValidationError as exc:
                raise ModelArtifactLoadError(str(exc)) from exc
            except OSError as exc:
                raise ModelArtifactLoadError("Cannot read local model artifact") from exc
            return manifest_bytes, model_bytes

        credential = self.credential or DefaultAzureCredential()
        token = credential.get_token(AZURE_STORAGE_SCOPE).token
        client = self.http_client or httpx.Client(timeout=60)
        close_client = self.http_client is None
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "x-ms-date": email.utils.formatdate(usegmt=True),
                "x-ms-version": AZURE_STORAGE_API_VERSION,
            }
            if binding.blob_etag is not None:
                headers["If-Match"] = binding.blob_etag
            manifest_uri = binding.artifact_uri
            if binding.blob_version_id is not None:
                parsed = urlparse(manifest_uri)
                manifest_uri = urlunparse(
                    parsed._replace(query=urlencode({"versionid": binding.blob_version_id}))
                )
            response = client.get(manifest_uri, headers=headers)
            response.raise_for_status()
            if binding.blob_etag is not None and response.headers.get("etag") != binding.blob_etag:
                raise ModelArtifactLoadError("Blob manifest ETag does not match assignment")
            if (
                binding.blob_version_id is not None
                and response.headers.get("x-ms-version-id") != binding.blob_version_id
            ):
                raise ModelArtifactLoadError("Blob manifest version does not match assignment")
            manifest_bytes = response.content
            if sha256_bytes(manifest_bytes) != binding.artifact_hash:
                raise ModelArtifactLoadError("Manifest SHA256 does not match assignment")
            try:
                manifest = ArtifactManifest.from_bytes(
                    manifest_bytes, expected_purpose=binding.model_purpose
                )
            except ArtifactValidationError as exc:
                raise ModelArtifactLoadError(str(exc)) from exc
            model_response = client.get(
                _model_blob_uri(binding.artifact_uri, manifest.model_file),
                headers={
                    "Authorization": f"Bearer {token}",
                    "x-ms-date": email.utils.formatdate(usegmt=True),
                    "x-ms-version": AZURE_STORAGE_API_VERSION,
                },
            )
            model_response.raise_for_status()
            return manifest_bytes, model_response.content
        except httpx.HTTPError as exc:
            raise ModelArtifactLoadError("Failed to download private model artifact") from exc
        finally:
            if close_client:
                client.close()


def load_model_artifact(
    *,
    binding: ArtifactBinding,
    cache_directory: Path,
    credential: TokenCredential | None = None,
    http_client: httpx.Client | None = None,
) -> MaterializedModelArtifact:
    return ModelArtifactLoader(
        cache_directory,
        credential=credential,
        http_client=http_client,
    ).load(binding)
