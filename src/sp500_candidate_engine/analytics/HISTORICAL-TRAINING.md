# Historical MEDIUM_20D challengers (non-promoting)

This is a **model-training** reconstruction seam, not an operational replay, a weekly
promotion retry, or a candidate/portfolio runner. Implemented and unit tested; **not
deployed or trained**. No provider collection, Azure mutation, active assignment, live
environment binding, weekly-v1 run, candidate, or report is changed by this implementation.

## Contract and isolation

- `historical_training_context.freeze_training_context` freezes an **explicitly reviewed**
  set of already-stored snapshot IDs into a reconstruction manifest/context. It does not
  pick the newest context, fetch missing data, invent source dates, or change observations.
  All parents and unambiguous per-dataset precedence must be supplied. Missing lineage,
  future snapshot/revision availability, future coverage, blocking quality issues, and
  ambiguous universe versions fail closed; freezing is one transaction.
- `historical_training.reconstruct_challenger` requires the context, manifest, both hashes,
  universe, anchor, historical cutoff, and a fresh reconstruction UUID. It creates a
  **new derived training context** bound to that same manifest. Its distinct context/export
  namespace prevents model-registry upserts from touching previous weekly-v1 exports/models.
  Reusing a UUID/output directory or derived DB context fails before another fit.
- It reuses `HistoricalQlibExportService`, raw Alpha158, the existing purged walk-forward
  evaluation, Ridge/LightGBM fitting, registry, weekly-v2 evaluator, and schema-v2 packaging.
  There is no shortcut model or custom estimator. As with the existing deployable artifact
  contract, if the winning shadow model is not LightGBM, packaging **fails** rather than
  relabelling Ridge weights or silently substituting another model.
- All features/evaluation rows end at the historical anchor. Only matured training and
  evaluation labels enter fitting/evaluation; the latest inference date does **not** need
  its forward 20-session label. Final train/validation labels are purged at their boundary.
  Ridge's fitted imputer/scaler use final train rows only; Alpha158 is raw and LightGBM
  has no fitted external processor. Nothing refits on prediction-day data.
- `fit_at`, `fit_completed_at`, `generated_at`, artifact creation, and DB `created_at`
  are real present-day times. Historical cutoff and simulated fold boundaries are
  separately named. Late acquisition is allowed only as reconstruction; source/revision
  publication availability is still fenced. Universe/GICS limitations are recorded.
- Policy is exactly `weekly-v2-20d-performance-suspended`: original performance values,
  `passed`, thresholds and `enforced=false` remain visible. Coverage >= 0.80, >= 3 test
  blocks, finite required metrics, source/PIT, purpose, feature dimensions and artifact
  hashes remain enforced. No current incumbent is queried or claimed beaten.
- Output is a local isolated schema-v2 manifest/weights plus `reconstruction.json`,
  bound by model ID and both artifact hashes. CLI also prints the provenance SHA256.
  Only SHADOW registrations are created. The seam never calls weekly finalization,
  promotion-decision writes, champion updates, CAS, active assignment, smoke or rollback.
  Those live activation safeguards remain unchanged, not bypassed. Failed work is retained
  with `FAILED`; retry with a new UUID, never overwrite the prior attempt.

`historical_safety` still defaults to strict operational replay. Allowing a newly fitted
artifact requires explicit reconstruction mode and historical training/data/processor
evidence. Operational replay continues to reject late observations and new artifacts.

## Historical anchors and prerequisites

Use actual preceding-weekend data anchors, **not** the scheduler's weekend ISO-week string:

| Signal sessions (inclusive) | Training data anchor | Conventional D+1 cutoff, UTC |
|---|---|---|
| 2026-09-30 .. 2026-10-02 | 2026-09-25 | 2026-09-26T09:30:00+00:00 |
| 2026-10-05 .. 2026-10-09 | 2026-10-02 | 2026-10-03T09:30:00+00:00 |
| 2026-10-12 .. 2026-10-14 | 2026-10-09 | 2026-10-10T09:30:00+00:00 |

The cutoff is an explicitly approved historical knowledge boundary, not a claim that
training actually ran then. Use the frozen context's exact verified cutoff. A boundary
after the preceding weekend is rejected. Holidays use the XNYS preceding session.
The example cutoff is not automatically substituted for an existing context's timestamp.

Read-only inventory on 2026-10-18 confirmed that the 2026-09-25 boundary has 490 eligible
daily price backfill snapshots/sessions (2024-10-11 .. 2026-09-25), 490 derived split
snapshots, 490 universe-backfill snapshots and 146 distinct historical universe versions
through 2026-09-21. Price source availability and universe announcement/effective-date
violations were zero in those bounded checks. This was **not** a completed full-manifest
readiness certificate. Subsequent recursive review found that derived split DELTAs point
to raw `massive_splits_backfill` parents, **not price parents**. Five/five/two required
parents exceed the Sep25/Oct2/Oct9 historical boundaries, respectively. For example parent
`a654c9c3-733c-5355-a274-b847848bd881` records availability
`2026-10-10T19:18:55.204158+00:00`, after even the Oct9 training cutoff.
The historical builds therefore **stopped before freezing or fitting**, as required by
the strict source/parent contract. Do not drop parents, backdate metadata or treat late raw
container acquisition as independently verified historical publication.
Small operational seven-snapshot contexts are not
substitutes for the historical training input. Historical anchors before October 8 need
an explicitly assembled rich manifest; do not select the newest context.

The existing generic daily freezer's newest-context selection is also not a safe substitute
for an explicit reviewed plan: a guarded Oct12 attempt selected 15 future-availability and
13 future-coverage snapshots. Its outer transaction rolled back completely (zero resulting
manifest/context rows). Explicit daily plans must retain complete lineage and their own
D+1 New York 05:30 cutoff; do not label them as weekly training contexts. No model,
weekly-run or active-assignment fingerprints changed during this authorized preflight.

Before execution, review the exact snapshot list, parent closure, source availability,
blocking quality issues, universe uniqueness, historical membership/GICS limitations,
two-year coverage, and the current approved code revision. A source revision that was
not published by the historical cutoff cannot be made eligible by changing its timestamp.
No automatic source collection/revision repair is provided.

## Freeze input without collection (future authorized execution only)

Export **metadata only** from read-only DB queries to a reviewed members JSON array.
Each entry must contain the real existing snapshot metadata and explicit precedence:

```json
[
  {
    "source_snapshot_id": "<existing UUID>",
    "dataset_code": "massive_grouped_daily_backfill",
    "snapshot_kind": "FULL",
    "lineage_role": "SINGLE",
    "precedence": 0,
    "parent_snapshot_id": null,
    "coverage_start": "2024-10-11",
    "coverage_end": "2024-10-11"
  }
]
```

The single entry above illustrates the schema; it is **not sufficient training input**.
Use the complete reviewed price history, derived split parent closure and historical
universe snapshots. DELTA members use `lineage_role=DELTA`; preserve BASELINE/SINGLE
semantics and strict dataset precedence. Do not use today's universe as historical data.
The supplied `universe_version_id` must be the latest eligible as-of version actually
present in this explicit manifest, not the latest version in the database.

After approval, in the repository root using the existing isolated analytics runtime:

```powershell
$py = '.\.venv-alpha158\Scripts\python.exe'
$id = [guid]::NewGuid().ToString()
# Set this to the reviewed latest universe UUID in this manifest.
$universe = '<approved universe UUID>'
& $py -m sp500_candidate_engine.analytics.historical_training_context `
  --members-file .\data\output\historical-models\sep25-reviewed-members.json `
  --reconstruction-id $id --signal-session 2026-09-30 --anchor-session 2026-09-25 `
  --training-cutoff '2026-09-26T09:30:00+00:00' --universe-version-id $universe |
  Set-Content .\data\output\historical-models\sep25-frozen.json
if ($LASTEXITCODE -ne 0) { throw 'Input freeze failed; do not train' }
```

Freezing writes only new immutable `ops.input_manifest`, members and reconstruction
context rows. It is a separate future-authorized mutation, **not a read-only command**.
Do not run it during preflight. Alternatively pass an already-approved rich reconstruction
context and its exact hashes directly to the training seam.

## Reconstruct once per anchor (future authorized execution only)

```powershell
$f = Get-Content .\data\output\historical-models\sep25-frozen.json -Raw | ConvertFrom-Json
& $py -m sp500_candidate_engine.analytics.historical_training `
  --reconstruction-id $f.reconstruction_id --signal-session $f.signal_session `
  --anchor-session $f.anchor_session --training-cutoff $f.training_cutoff `
  --execution-context-id $f.execution_context_id --input-manifest-id $f.input_manifest_id `
  --manifest-hash $f.manifest_hash --context-hash $f.context_hash `
  --universe-version-id $f.universe_version_id --output-root .\data\output\historical-models\outputs
if ($LASTEXITCODE -ne 0) { throw 'Challenger reconstruction failed; do not score' }
```

Repeat with a fresh UUID and reviewed per-anchor members/context for October 2 and
October 9, representative signal dates October 5 and October 12. No bulk execution is
implicit. Store output directories and stdout JSON with the execution evidence.
Settings use the normal approved in-process Entra DB authentication; the executing role
must have context/export/SHADOW registration grants. Do not commit credentials or rely
on provider keys. Schema migrations already used by the normal analytics engine are
prerequisites. Preserve all live immutable artifact environment bindings.

### Runtime choice verified read-only

`rg-ai-project / sp500-candidate-training` is the existing manual Container Apps Job:
2 CPU, 4 GiB, 14400-second timeout, image digest
`sha256:f0133c29fb79635bb893fdfede88ec7186d11e0bad45dadd1d10b9cb30ca2d7e`.
Its default entrypoint is **promotion-capable `analytics.weekly_job`**; it does not contain
this change. It has no mounted volumes and runs as non-root. **Do not start that default
job, change its template, deploy, or assume its output is persistent.**

For this isolated reconstruction, the verified local `.venv-alpha158` runtime already
has pyqlib 0.9.7, LightGBM 4.7.0, pandas 3.0.6, pyarrow 23.0.1 and psycopg 3.3.6.
It provides a writable persistent project-local output directory and can use the approved
private DB connection. Prefer the explicit commands above after authorization and DB-role
validation. No install or production deployment is needed merely to expose the CLI.
Both CLI `--help` commands are safe and do not connect to the DB.

If cloud execution is later chosen, first approve an immutable image containing this
commit, a writable persistent non-temporary output mount, and artifact retention.
Override the entrypoint to `python -m sp500_candidate_engine.analytics.historical_training`
for **one execution**, with the same explicit arguments; preserve identity, private network,
environment and resource sizing. Do not alter the operational job's default entrypoint or
live artifact bindings. These cloud prerequisites are not implemented/deployed here.

## Independent Quant20 artifact override

Validate the original schema-v2 manifest, sidecar and pinned checksums **before** using the
existing `MaterializedModelArtifact` override. Example service-level admission:

```python
from pathlib import Path
from datetime import date
from sp500_candidate_engine.analytics.historical_training import validate_reconstructed_artifact
from backend.app.services.model_artifacts import ArtifactBinding, ModelArtifactLoader

manifest_path = Path(approved_manifest_path)
validate_reconstructed_artifact(
    manifest_path=manifest_path,
    manifest_sha256=approved_manifest_sha256,
    provenance_sha256=approved_provenance_sha256,
    signal_session=date(2026, 9, 30),
    knowledge_mode="HISTORICAL_RECONSTRUCTION",
)
artifact_override = ModelArtifactLoader(Path(r"data\output\historical-models\cache")).load(
    ArtifactBinding("MEDIUM_20D", manifest_path.resolve().as_uri(), approved_manifest_sha256)
)
```

Pass this materialized object into the existing Quant inference `artifact_override`
seam with the independently frozen **prediction-day** reconstruction context. Do not
replace the active assignment/environment bindings to make the public API choose it.
Pin the manifest/provenance hashes in the later stage contract; validating only the
model's UUID does not bind its training history. The admission helper rejects operational
replay, modified weights/provenance, and another signal week's artifact.

The current independent stage request API itself does not expose a request-level artifact
override; this model-only change does not alter that API. Use its existing internal
override seam through a separately approved pinned contract integration, not a global
environment edit or an unvalidated client-supplied path.

Only subsequent independent Quant20, LLM20(v6), then Fusion20 are intended consumers.
This implementation does not run any of them. It never requests a forward 20D outcome
for an inference date and does not implement portfolio simulation, October 15 signals,
candidate/report deletion, or external analysis.
