# Historical MEDIUM_20D challengers (non-promoting)

This is a **model-training** reconstruction seam, not an operational replay, a weekly
promotion retry, or a portfolio runner. The separately approved research-only DAILY
eligibility/inference extension is described below. Implemented and unit tested; the
explicit Oct9 Sunday alternative below has a verified local **SHADOW** artifact, not
a deployment or promotion. No provider collection, Azure mutation, active assignment, live
environment binding, weekly-v1 run, existing candidate, or report is changed.

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
  evaluation, Ridge/LightGBM fitting, registry and weekly-v2 evaluator. LightGBM keeps
  byte-compatible schema-v2 packaging; the user-approved actual Ridge winner uses the
  data-only schema-v3 contract below. Neither family is substituted for the winner.
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
- Output is a local isolated versioned manifest/weights plus `reconstruction.json`,
  bound by model ID and both artifact hashes. CLI also prints the provenance SHA256.
  Only SHADOW registrations are created. The seam never calls weekly finalization,
  promotion-decision writes, champion updates, CAS, active assignment, smoke or rollback.
  Those live activation safeguards remain unchanged, not bypassed. Failed work is retained
  with `FAILED`; retry with a new UUID, never overwrite the prior attempt.

`historical_safety` still defaults to strict operational replay. Allowing a newly fitted
artifact requires explicit reconstruction mode and historical training/data/processor
evidence. Operational replay continues to reject late observations and new artifacts.

## Historical anchors and prerequisites

### Certified-only issuer quarantine (isolated reconstruction)

`certified_scope.py` supports a conservative data-quality subset without changing
ordinary source-time semantics. The separately approved research-policy dispatch in
`SourceRepository` is explicit and does not alter its untagged/default state query:

- Determine exclusions only from the immutable proof matrix and issuer ownership, never
  from prices, labels, model scores or later outcomes. APH, CVNA, DD, FTV, HON, LEN, MNST,
  NOW and PANW are the nine reviewed issuers. Expand to every share class and all of each
  issuer's actions. Preserve all twelve certificates; DD's certified reverse split is
  excluded too, leaving eleven admitted split facts. All 21 original rows remain intact.
- Preserve the original universe records/memberships. The target cohorts remain 503;
  their source-quality subset is 494/503 = 98.2107%, not a rewritten 494-member universe.
  Scoped FULL price observations physically omit excluded issuers before preprocessing,
  so existing Quant history and LLM v6 target-price gates reject the same issuers without
  passing Quant ranks into LLM. Keep explicit dated scope/reason/completeness audits.
- A new FULL projection is complete **only for its declared certified eligible scope**.
  Original carrier snapshots/parents/hashes are retained as audit provenance, not admitted
  as late data. New event rows use verified original SEC acceptance/publication bounds,
  not effective-date midnight or archive dates. Price information timestamps are copied
  from the existing admitted source; no new source-date assumption is introduced.
  Projection `generated_at`, `fetched_at`, `created_at` and observation clocks are NOW.
  `source_available_at` is the maximum original public-information bound of admitted
  data, explicitly not the mint/publication time of this newly generated representation.
- `UNKNOWN` adjustment flags are not relabelled as raw. Only already-qualified
  `UNADJUSTED` price/volume observations are admitted; any remaining gaps stay missing
  and are not forward-filled.
- Training caches original point-in-time membership separately. Quarantined/unknown
  label values are never computed; evaluation reindexes only the reference slots.
  Historical membership sizes actually vary 501–504, so the applied denominator is the
  sum of `max(original date membership, 503)`. This preserves every original member and
  never shrinks the requested 503 reference. Ordinary unscoped evaluation is unchanged.
  Coverage >= 0.8, >=3 test blocks, finite metrics, purges, processor fitting and purpose
  contracts remain unchanged. Scoped model admission requires the matching prediction
  quality-mask hash.

Actual Sep25 and Oct2 fits each registered momentum/Ridge/LightGBM SHADOW baselines.
LightGBM coverage was `147711 / 151911 = 0.972352232557221`, with 15 test blocks.
Both unchanged shadow comparisons selected Ridge (Rank IC `-0.0058873788`) over
LightGBM (`-0.0071800492`). The initial LightGBM-only serving gate stopped both bindings.
Subsequently the user explicitly selected the **actual winning Ridge**, not LightGBM
substitution. Both existing fitted winners are now bound without another fit.

Official-reference candidate readiness was a separate failed gate: existing `instrument_state`
rows
are zero for Sep30–Oct8, where at least 20 candidate-eligible instruments are required.
The two training contexts are explicitly **training-only, not candidate-ready**; no
listing-state inference, current-metadata backdating or reference-time bypass was used.
Oct9 has 503 globally valid states. A trained weight file is not permission to bypass
either the serving-family or candidate-reference gate. The later research-only policy is
an explicit, differently named eligibility contract, not a claim those official rows exist.

### Actual Ridge serving (schema v3)

- Model IDs remain `861b5f38-f10c-565f-989d-7253d34c13f5` (Sep25) and
  `3fc6ebf4-03ee-5624-bfab-cd259fe2accb` (Oct2). SHADOW, source/export bindings,
  original checkpoint hashes, actual Oct18 fit times, and selected metrics are unchanged.
- `ridge.json` contains only fitted numeric arrays: median-imputer statistics,
  StandardScaler means/scales, Ridge coefficients/intercept, dtypes and exact feature order.
  The supported contract requires `keep_empty_features=true`, no missing indicators,
  and centering/scaling enabled; empty training columns retain their fitted zero statistic
  and scale. Unsupported transformations, nonfinite arrays, invalid scales, dimensions,
  changed feature order, infinities and invalid JSON fail closed. Prediction never fits.
- Schema v3 adds `model_family=ridge` and `training_artifact_sha256`. The latter binds
  the **original registered joblib checksum**; `model_sha256` binds the separate safe JSON.
  The original registry row/URI/hash is not rewritten or renamed. Existing schema v2
  serialization, LightGBM loader, live model301785 and app bindings stay unchanged.
  Generic packaging requires explicit `allow_ridge=True` (CLI `--allow-ridge`); the
  reconstruction binder opts in, but normal weekly packaging defaults do not change.
- Serving and downloads never deserialize pickle/joblib. The bounded offline conversion
  used only the two user-approved, locally trained, registry-hash-verified checkpoints.
  New reconstruction training exports arrays directly from the fitted in-memory pipeline.
  The packager also verifies the retained checkpoint bytes against the registered hash.
- Each actual conversion compared 520 predictions against the original sklearn pipeline:
  real stored Alpha158 rows, all/partial NaNs, zero values and float32/float64. Maximum
  absolute differences were `4.0978193283081055e-8` and `6.705522537231445e-8`
  (rtol `1e-6`, atol `1e-7`); fitted statistics were copied, not recomputed.
- `bind_fitted_challenger` revalidates frozen source/context/export checksums, registered
  selected-model identity, unchanged winner comparison, retained weekly-v2 gates, source,
  label and processor clocks before packaging. It performs no training or DB writes.
  Binding-time source hashes are not contemporaneous training-code attestations for old
  checkpoints. New fits capture code hashes before fitting; retained checkpoints explicitly
  record that limitation. The first two schema-v3 bindings preserve their immutable bytes;
  their separately pinned conversion audit clarifies the legacy `training_code_sha256`
  field as binding-time hashes, not evidence that the newer serving code trained them.
- New registry: `data\output\historical-models\execution-20261018\artifact-registry-ridge-v1.json`.
  The earlier accepted `artifact-registry.json` remains immutable. The new registry's READY
  means **artifact admission**, not permission to ignore prediction-context eligibility.

### Approved research-only DAILY eligibility (2026-10-18)

The historical status table is like a dated identity/status record: existing dated prices
and S&P500 membership do not themselves supply that missing official record. The approved
alternative explicitly uses those two existing facts to define **research eligibility**;
it does not manufacture an old ACTIVE/LISTED record.

- Policy `historical-membership-price-research-v1`; classification
  `EXPERIMENTAL_RESEARCH_ELIGIBILITY`; `official_historical_state_verified=false`.
  It requires an explicitly new DAILY context with this config version, one certified
  immutable scope, `HISTORICAL_RECONSTRUCTION`, and exact D+1 NY05:30 cutoff.
  Operational replay, untagged contexts, normal timers and weekly defaults do not opt in.
- Original dated membership/issuer identity remains unchanged. Admission requires the
  exact target-session, manifest-bound valid UNADJUSTED OHLCV with publication before
  cutoff, known adjustment flags, no conflicting versions and ordinary action/quality gates.
  The nine-issuer quarantine remains context-scoped; all 503 original members remain in
  membership/audit, leaving at most 494 before target-price gates. Actual missing target
  prices remain exclusions (Oct6: 492 eligible; two additional missing-price records).
  A backfill coverage date is not proof of qualified target prices: the bounded Oct8/9
  correction explicitly reviewed same-day operational FULLs even where the backfill
  claimed that date but contained UNKNOWN observations. It admits only already-stored
  rows/snapshots available by cutoff and preserves the failed Oct8 attempt.
  Oct9 also required those qualified Oct8 observations for the unchanged warm-up gate;
  its first failed Quant/context remains preserved, and a new context completed.
  Quant additionally
  retains complete warm-up/finite-feature gates. No feature/label fill is added.
- New contexts use actual NOW generation/observation times; `ref.instrument_state` and
  all original source rows/timestamps are untouched. Official status/exchange stay null,
  not inferred from a current record. Each Quant candidate carries the experimental reason
  code, and the result/contract/context retain the explicit classification.
- Both Quant and independent LLM consume the same source-quality eligibility gates.
  The LLM records a non-rubric UNIVERSE eligibility audit link, **not a fabricated
  INSTRUMENT_STATE** link. Prices and Quant scores never become v6 rubric evidence.
- Freezing the context does not execute LLM/Fusion or external consumers. Internal Quant
  execution uses an explicitly pinned new registry in child-process environment only.
  No production deployment or active assignment is needed for local internal stages.

Actual final checks completed for all eight dates (maximum two dates concurrently):

| Signal | New research context | Eligible target prices | Fully gated scores | Quant candidates |
|---|---|---:|---:|---:|
| Sep30 | `6b40ea01-9816-5e58-a6fa-8109b31ad247` | 494 | 484 | 20 |
| Oct1 | `ae0177e9-a4e2-52d5-aabe-2b124d1e6041` | 494 | 484 | 20 |
| Oct2 | `c701ca8d-db2d-5578-9c4d-b165119b4388` | 494 | 484 | 20 |
| Oct5 | `16f1cd57-073c-5764-b116-aebf2836f4fc` | 494 | 484 | 20 |
| Oct6 | `51c7b08b-6ad8-59eb-b110-2babd870c881` | 492 | 482 | 20 |
| Oct7 | `99e18263-6030-5af4-92f0-363e9087e0aa` | 494 | 481 | 20 |
| Oct8 | `13b73a76-8abb-5d36-a77f-2011a9e71433` | 494 | 481 | 20 |
| Oct9 | `d381ef8f-74ca-5bea-87ff-3188a8d99a7e` | 494 | 481 | 20 |

All rows are `EXPERIMENTAL_RESEARCH_ELIGIBILITY`, **not verified historical reference
status**. Original membership is 503; nine quarantined issuers remain absent from every
score/candidate. Quant's additional warm-up/finite-feature exclusions do not define the
independent LLM ranking. No LLM or Fusion was executed by this reconstruction runner.
Read-only final verification also checked original model rows, all 21 original actions,
original snapshot metadata, model301785, official-state counts, and weekly/active state.

The complete private execution handoff is
`data\output\historical-models\execution-20261018\handoff-ridge-research-final.json`.
It pins actual selection/scoring/stage IDs, reviewed members, per-asset exclusions,
logs and safe artifact hashes. The accepted old registry remains
`6544fd1dc6277d46f630a04371377220f7311f2d27f0789b42d1687f529fd90e`;
the separate Ridge registry is
`cdcc452851ae446ab1abd30cdb81379fbfdb4e71efcc9e914e51a87ca29a02f7`.
The first Sep30 receipt's legacy member counter is clarified in the handoff; official
state is still unverified/zero, never 503 inferred official records.

For an explicitly approved internal stage, use the helper with a **new** attempt UUID;
do not change live appsettings or run the promotion-capable training job:

```powershell
& .\.venv-alpha158\Scripts\python.exe `
  .\data\output\historical-models\execution-20261018\run_research_quant_stage.py `
  --registry-file .\data\output\historical-models\execution-20261018\artifact-registry-ridge-v1.json `
  --frozen <actual frozen.json path from handoff> --attempt-id <new UUID>
```

The eight stages are already successful; do not execute them again unnecessarily.
Parent-owned independent v6 LLM preparation must use this research-aware code/context,
not an older deployed runtime that still requires official instrument-state joins.
Ordinary result-read APIs need no deployment for the existing generic model/reason fields.

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

### Explicit Oct9-only Sunday alternative

The versioned weekly policy does not fix training knowledge to Saturday 05:30. The existing
weekend scheduler accepts Saturday/Sunday, and the reconstruction validator requires a
completed explicit boundary before Monday 00:00 New York, with the preceding Friday
data anchor unchanged. The operational weekly API still accepts only its own eligible
operational contexts; it is **not** used for this historical alternative.

The 2026-10-18 authorized alternative uses a **new** context with
`training_cutoff=2026-10-11T09:30:00+00:00` (Sunday 05:30 New York),
`anchor_session=2026-10-09`, and first signal `2026-10-12`. The latest required archive
was actually available `2026-10-11T05:07:30.536548+00:00`; all 21 normalized action
versions were observed by `2026-10-10T19:18:55.204158+00:00`. Read-only review admitted
1,506 snapshots and 500 price sessions ending Oct9 with zero future rows or blocking
quality issues. All original parents remain in the closed input. No new projection
semantics, inferred old publication dates, or changed Saturday identities are needed.

Actual reconstruction starts now, not on Sunday. The chosen knowledge-boundary rationale,
new request/context IDs, reviewed members and actual start time are separately recorded
under the ignored execution artifacts. The same unmodified training, label, processor,
weekly-v2 integrity and artifact checks apply. This does **not** make Oct10 archives
eligible for the Sep25 or Oct2 weekends; those earlier reconstructions remain blocked.

The first attempt failed before fitting with Windows path-length error 206. Its failed
export and audit remain intact. A fresh UUID and shorter project-local output root
`data\output\w20` completed the unchanged workflow and retained weekly-v2 gates.
Selected LightGBM `301785d6-8512-514a-972c-b4a734e7c3b5` remains SHADOW:
coverage `1.0`, 16 test blocks, Rank IC `0.0060716212`. The Rank IC threshold is still
recorded, not enforced under the approved policy. All prior model-row hashes and
weekly/active-assignment fingerprints remained unchanged; only three new SHADOW baseline
registrations were added. The immutable manifest and provenance passed reconstruction
admission for Oct12–14. This is not certification of a new historical split-projection
policy or authorization to promote the artifact.

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
  --universe-version-id $f.universe_version_id --output-root .\data\output\w20
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

Prediction-day context curation must include valid target prices. A rich historical
backfill manifest alone can still stop on Friday Oct9 and omit the operational Oct12–14
bars. Do not exclude the entire `massive_grouped_daily` family merely because a generic
newest-context union included future members: add the exact existing eligible recent
FULL observations with coverage ending on/before D and source availability on/before
D+1 New York 05:30. Preserve prior history/evidence and complete parent lineage, use
explicit deterministic precedence, and retain the existing normalized-row temporal and
blocking-quality checks. No provider collection or fixed original context is changed.

Freeze a **new** manifest/context and require `SourceRepository.read_bars(D)` to return
rows and intersect at least 20 eligible universe instruments before marking it price-ready.
The initial three incomplete contexts are preserved. Their corrected successors returned
503 target-price rows and 503 eligible target-price instruments each. This validates
price input readiness, not successful LLM, Quant or Fusion execution. Keep runtime
artifacts/workspaces under ignored, short project-local paths on Windows.

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
