# Orchestrator telemetry KQL runbook

Updated: 2026-10-13

The Function App writes one JSON object per pipeline trace. The emitter allowlists only
correlation and lifecycle fields; secrets, raw payloads, report bodies, resource IDs, and
exception messages are excluded. Durable orchestrators schedule the
`emit_pipeline_telemetry` activity, so replay does not duplicate logging side effects.

The examples work in a workspace-based Application Insights resource (`AppTraces`) and
the Application Insights Logs experience (`traces`). Replace the time range as needed.
Run the common projection and the selected query in the same query tab. These queries
are read-only; deployment validation in the target workspace is still required.

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
    EventTime = todatetime(T.timestamp);
```

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
