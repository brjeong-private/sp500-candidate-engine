# Orchestrator telemetry KQL runbook

Updated: 2026-10-16

The Function App writes one JSON object per pipeline trace. The emitter allowlists only
correlation and lifecycle fields; secrets, raw payloads, report bodies, resource IDs, and
exception messages are excluded. Durable orchestrators schedule the
`emit_pipeline_telemetry` activity, so replay does not duplicate logging side effects.

The examples work in a workspace-based Application Insights resource (`AppTraces`) and
the Application Insights Logs experience (`traces`). Replace the time range as needed.
Run the common projection and the selected query in the same query tab. These queries
are read-only; deployment validation in the target workspace is still required.

The weekly retraining flow is implemented and covered by focused local tests, but the
weekly changes have not been deployed. The code allowlist accepts `iso_week`,
`weekly_run_id`, and `job_execution_name`; it still rejects secrets, ARM resource IDs,
raw API payloads, and exception messages. Weekly lifecycle emission from the Durable
workflow, allowlist output, and collection in the target workspace remain validation
items. An empty weekly query is therefore not evidence of a successful run.

## Common projection

Start each query with this projection:

```kusto
let PipelineTelemetry = union isfuzzy=true AppTraces, traces
| extend Raw = tostring(column_ifexists("Message", column_ifexists("message", "")))
| where Raw startswith "{"
| extend T = parse_json(Raw)
| where tostring(T.event) startswith "pipeline."
| extend
    Event = tostring(T.event),
    ParentInstanceId = tostring(T.parent_instance_id),
    ModelInstanceId = tostring(T.model_instance_id),
    TargetSession = tostring(T.target_session),
    ModelPurpose = tostring(T.model_purpose),
    CandidateProcessRunId = tostring(T.candidate_process_run_id),
    SelectionRunId = tostring(T.selection_run_id),
    DailyAnalysisId = tostring(T.daily_analysis_id),
    State = tostring(T.state),
    Stage = tostring(T.stage),
    Remediated = tobool(T.remediated),
    IsoWeek = tostring(T.iso_week),
    WeeklyRunId = tostring(T.weekly_run_id),
    JobExecutionName = tostring(T.job_execution_name),
    EventTime = todatetime(T.timestamp);
```

## Weekly retraining status

Use this query after weekly lifecycle events are connected to the replay-safe emitter.
It intentionally projects only allowlisted identifiers and states.

```kusto
PipelineTelemetry
| where isnotempty(IsoWeek) or isnotempty(WeeklyRunId)
| summarize arg_max(
    EventTime, Event, State, Stage, ModelInstanceId, WeeklyRunId, JobExecutionName)
    by IsoWeek, ParentInstanceId, ModelPurpose
| order by IsoWeek desc, ParentInstanceId asc, ModelPurpose asc
```

Expected correlation IDs are `candidate-weekly-YYYY-Www` for the parent and
`candidate-weekly-YYYY-Www-{MODEL_PURPOSE}` for children. SHORT and MEDIUM run
sequentially but have independent outcomes, so alerting must not infer that a SHORT
failure means MEDIUM was not attempted.

## Weekly timeouts and incumbent retention

```kusto
PipelineTelemetry
| where isnotempty(WeeklyRunId)
| where State == "TIMED_OUT"
| project EventTime, IsoWeek, ParentInstanceId, ModelInstanceId,
    ModelPurpose, WeeklyRunId, JobExecutionName, Stage
| order by EventTime desc
```

A timeout at `training_job` or `promotion` is terminal for that model child. The
orchestrator does not update the active assignment on timeout, so the Candidate
PostgreSQL incumbent remains authoritative. Confirm retention against the Candidate
assignment API/database during deployment validation; telemetry alone does not prove
pointer state.

## Dual-model status

```kusto
PipelineTelemetry
| where Event in ("pipeline.parent.terminal", "pipeline.model.terminal")
| summarize arg_max(EventTime, State, Stage, ModelInstanceId)
    by TargetSession, ParentInstanceId, ModelPurpose
| order by TargetSession desc, ParentInstanceId asc, ModelPurpose asc
```

## Parent and model durations

```kusto
PipelineTelemetry
| where Event in (
    "pipeline.parent.started", "pipeline.parent.terminal",
    "pipeline.model.started", "pipeline.model.terminal")
| summarize
    StartedAt = minif(EventTime, State == "STARTED"),
    FinishedAt = maxif(EventTime, State != "STARTED"),
    TerminalState = take_anyif(State, State != "STARTED")
    by ParentInstanceId, ModelInstanceId, TargetSession, ModelPurpose
| extend Duration = FinishedAt - StartedAt
| where isnotnull(FinishedAt)
| order by FinishedAt desc
```

## Existing-run skips

```kusto
PipelineTelemetry
| where Event == "pipeline.model.skipped_existing"
| project EventTime, TargetSession, ParentInstanceId, ModelInstanceId,
    ModelPurpose, SelectionRunId, State, Stage
| order by EventTime desc
```

`SKIPPED_EXISTING` means a complete selection for the exact target session and model
was found before Candidate submission. No Candidate POST or Portal batch is made; the
model sends only its terminal email.

## Guardian remediations

```kusto
PipelineTelemetry
| where Event in ("pipeline.guardian.remediation", "pipeline.guardian.terminal")
| where Remediated
| project EventTime, Event, State, Stage, Remediated
| order by EventTime desc
```

The 15-minute guardian checks readiness and applies only the approved start,
minimum-replica, and private-Storage remediation contract. It does not start or retry
the dual parent orchestration.

## Pipeline failures

```kusto
PipelineTelemetry
| where Event endswith ".terminal" and State in ("FAILED", "PARTIAL_FAILED", "TIMED_OUT")
| project EventTime, Event, TargetSession, ParentInstanceId, ModelInstanceId,
    ModelPurpose, CandidateProcessRunId, SelectionRunId, DailyAnalysisId, State, Stage
| order by EventTime desc
```

## Email success and failure

```kusto
PipelineTelemetry
| where Event == "pipeline.email.terminal"
| summarize Count = count() by bin(EventTime, 1h), State, Stage, ModelPurpose
| order by EventTime desc
```
