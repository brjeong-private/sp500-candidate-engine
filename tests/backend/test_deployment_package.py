from __future__ import annotations

import hashlib
import json
from zipfile import ZipFile

from backend import prepare_deployment


def test_source_package_excludes_secrets_and_outputs(tmp_path, monkeypatch):
    for directory in (".azure", "backend", "src", "config", "sql"):
        (tmp_path / directory).mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("test project", encoding="utf-8")
    (tmp_path / "backend" / "requirements.txt").write_text(".[backend,analytics]", encoding="utf-8")
    (tmp_path / "backend" / "app.py").write_text("print('test')", encoding="utf-8")
    (tmp_path / "sql" / "018_multi_model_support.sql").write_text(
        "SELECT '018_multi_model_support';", encoding="utf-8"
    )
    (tmp_path / "sql" / "020_backend_pipeline_idempotency.sql").write_text(
        "SELECT '020_backend_pipeline_idempotency';", encoding="utf-8"
    )
    (tmp_path / "backend" / ".env").write_text(
        "BACKEND_API_KEY=test-backend-token", encoding="utf-8"
    )
    (tmp_path / ".env").write_text(
        "PGHOST=localhost\nPGDATABASE=test\nMASSIVE_API_KEY=test-provider-token\n"
        "ALPHA_VANTAGE_API_KEY=test-alpha-token\nHTTP_USER_AGENT=test-agent\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prepare_deployment, "ROOT", tmp_path)
    artifact_dir = tmp_path / "data" / "backend-artifacts" / "models"
    for purpose in ("short_5d", "medium_20d"):
        purpose_dir = artifact_dir / purpose
        purpose_dir.mkdir(parents=True)
        (purpose_dir / "manifest.json").write_text(
            '{"schema_version": 2}', encoding="utf-8"
        )
    for name in (
        "PGHOST",
        "PGDATABASE",
        "MASSIVE_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "BACKEND_API_KEY",
        "HTTP_USER_AGENT",
    ):
        monkeypatch.delenv(name, raising=False)
    prepare_deployment.main()
    with ZipFile(tmp_path / ".azure" / "backend-source.tmp.zip") as archive:
        assert "requirements.txt" in archive.namelist()
        assert "backend/app.py" in archive.namelist()
        assert "sql/018_multi_model_support.sql" in archive.namelist()
        assert "sql/020_backend_pipeline_idempotency.sql" in archive.namelist()
        assert not any(".env" in name for name in archive.namelist())
        assert not any(b"test-provider-token" in archive.read(name) for name in archive.namelist())
    parameters = json.loads(
        (tmp_path / ".azure" / "backend.parameters.tmp.json").read_text(encoding="utf-8")
    )
    assert parameters["parameters"]["location"]["value"] == "koreacentral"
    assert parameters["parameters"]["apiKey"]["value"] == "test-backend-token"
    assert (
        parameters["parameters"]["candidateShortManifestSha256"]["value"]
        == hashlib.sha256(
            (artifact_dir / "short_5d" / "manifest.json").read_bytes()
        ).hexdigest()
    )
    assert (
        parameters["parameters"]["candidateMediumManifestSha256"]["value"]
        == hashlib.sha256(
            (artifact_dir / "medium_20d" / "manifest.json").read_bytes()
        ).hexdigest()
    )
