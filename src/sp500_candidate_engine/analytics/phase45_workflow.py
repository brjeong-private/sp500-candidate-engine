from __future__ import annotations

import hashlib
import json
import uuid
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from sp500_candidate_engine.analytics.baselines import (
    RidgeBaseline,
    compute_momentum_scores,
)
from sp500_candidate_engine.analytics.config import VersionedConfig
from sp500_candidate_engine.analytics.evaluation import (
    WalkForwardSpec,
    build_walk_forward_folds,
    dedupe_walk_forward_predictions,
    evaluate_predictions,
)
from sp500_candidate_engine.analytics.features import (
    Alpha158FeatureService,
    normalize_alpha158_frame,
)
from sp500_candidate_engine.analytics.model_registry import (
    ModelRegistration,
    ModelRegistry,
)
from sp500_candidate_engine.analytics.score_repository import ScoreRepository
from sp500_candidate_engine.analytics.scoring import rank_daily_scores
from sp500_candidate_engine.analytics.training import train_qlib_lightgbm
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, _canonical_hash
from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.selection.policy import (
    CandidateMetadata,
    SelectionPolicy,
    select_candidates,
)
from sp500_candidate_engine.selection.repository import SelectionRepository
from sp500_candidate_engine.selection.service import candidate_result_payload


@dataclass(frozen=True)
class PreparedTrainingData:
    features: pd.DataFrame
    labels: pd.DataFrame
    momentum: pd.Series
    metadata: pd.DataFrame
    feature_columns: tuple[str, ...]


@dataclass(frozen=True)
class Phase45Summary:
    experiment_key: str
    experiment_dir: Path
    export_run_id: uuid.UUID
    model_version_id: uuid.UUID
    scoring_run_id: uuid.UUID
    selection_run_id: uuid.UUID
    selected_shadow_model: str
    promotion_gate_passed: bool
    metrics: dict[str, dict[str, object]]
    candidate_path: Path
    candidate_count: int
    price_session_date: date
    model_purpose: str = "SHORT_5D"
    prediction_horizon_sessions: int = 5
    return_policy: str = "PRICE_RETURN"
    scorecard_quality_gate_passed: bool = False


@dataclass(frozen=True)
class TrainingWorkflowSummary:
    experiment_key: str
    experiment_dir: Path
    export_run_id: uuid.UUID
    model_version_id: uuid.UUID
    selected_shadow_model: str
    metrics: dict[str, dict[str, object]]
    model_purpose: str
    prediction_horizon_sessions: int
    return_policy: str
    scorecard_quality_gate_passed: bool


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_symbol(instrument_id: uuid.UUID) -> str:
    return f"I{instrument_id.hex.upper()}"


class TrainingDataRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def load(
        self,
        *,
        export_run_id: uuid.UUID,
        calendar: tuple[pd.Timestamp, ...],
    ) -> tuple[pd.DataFrame, pd.DataFrame, dict[pd.Timestamp, set[str]], pd.DataFrame]:
        with self.database.connect() as connection:
            export = connection.execute(
                """
                SELECT execution_context_id
                FROM analytics.qlib_export_run
                WHERE export_run_id = %s AND status = 'SUCCEEDED'
                """,
                (export_run_id,),
            ).fetchone()
            if export is None:
                raise RuntimeError(f"Unknown successful export: {export_run_id}")
            context_id = export["execution_context_id"]
            price_rows = connection.execute(
                """
                SELECT
                    instrument_id, session_date, open, close
                FROM analytics.qlib_daily_value
                WHERE export_run_id = %s
                ORDER BY instrument_id, session_date
                """,
                (export_run_id,),
            ).fetchall()
            benchmark_rows = connection.execute(
                """
                WITH ranked AS (
                    SELECT
                        benchmark.*,
                        row_number() OVER (
                            PARTITION BY benchmark.session_date, benchmark.source_id
                            ORDER BY imm.precedence DESC, benchmark.revision_no DESC
                        ) AS selected_revision
                    FROM ops.execution_context ec
                    JOIN ops.input_manifest_member imm
                      ON imm.input_manifest_id = ec.input_manifest_id
                    JOIN market.benchmark_daily_bar benchmark
                      ON benchmark.source_snapshot_id = imm.source_snapshot_id
                    WHERE ec.execution_context_id = %s
                      AND benchmark.benchmark_code = 'SPY'
                      AND benchmark.source_available_at <= ec.cutoff_at
                )
                SELECT session_date, open, close
                FROM ranked
                WHERE selected_revision = 1
                ORDER BY session_date
                """,
                (context_id,),
            ).fetchall()
            universe_rows = connection.execute(
                """
                SELECT DISTINCT
                    uv.as_of_date, um.instrument_id, instrument.issuer_id,
                    um.symbol, um.sector
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                 AND imm.dataset_code = ANY(%s::text[])
                JOIN ref.universe_version uv
                  ON uv.source_snapshot_id = imm.source_snapshot_id
                JOIN ref.universe_member um
                  ON um.universe_version_id = uv.universe_version_id
                JOIN ref.instrument instrument
                  ON instrument.instrument_id = um.instrument_id
                WHERE ec.execution_context_id = %s
                ORDER BY uv.as_of_date, um.instrument_id
                """,
                (["sp500_universe_backfill", "sp500_universe"], context_id),
            ).fetchall()

        prices = pd.DataFrame(price_rows)
        prices["datetime"] = pd.to_datetime(prices.pop("session_date"))
        prices["instrument_id"] = prices["instrument_id"].map(
            lambda value: uuid.UUID(str(value))
        )
        prices[["open", "close"]] = prices[["open", "close"]].astype(float)
        prices["instrument"] = prices["instrument_id"].map(_stable_symbol)
        prices = prices.set_index(["datetime", "instrument"]).sort_index()

        benchmark = pd.DataFrame(benchmark_rows)
        if benchmark.empty:
            benchmark = pd.DataFrame(
                index=pd.DatetimeIndex(calendar),
                columns=["open", "close"],
                dtype=float,
            )
        else:
            benchmark["datetime"] = pd.to_datetime(benchmark.pop("session_date"))
            benchmark[["open", "close"]] = benchmark[["open", "close"]].astype(float)
            benchmark = benchmark.set_index("datetime").sort_index()
            benchmark = benchmark.reindex(pd.DatetimeIndex(calendar))

        versions: dict[pd.Timestamp, list[dict[str, object]]] = {}
        for row in universe_rows:
            as_of = pd.Timestamp(row["as_of_date"])
            versions.setdefault(as_of, []).append(dict(row))
        version_dates = sorted(versions)
        membership: dict[pd.Timestamp, set[str]] = {}
        for session in calendar:
            position = bisect_right(version_dates, session) - 1
            membership[session] = (
                {
                    _stable_symbol(uuid.UUID(str(row["instrument_id"])))
                    for row in versions[version_dates[position]]
                }
                if position >= 0
                else set()
            )
        latest_rows = versions[version_dates[-1]]
        metadata = pd.DataFrame(
            [
                {
                    "instrument_id": uuid.UUID(str(row["instrument_id"])),
                    "issuer_id": uuid.UUID(str(row["issuer_id"])),
                    "instrument": _stable_symbol(
                        uuid.UUID(str(row["instrument_id"]))
                    ),
                    "symbol": str(row["symbol"]),
                    "sector": row["sector"],
                }
                for row in latest_rows
            ]
        ).set_index("instrument")
        return prices, benchmark, membership, metadata


def _build_labels(
    *,
    prices: pd.DataFrame,
    benchmark: pd.DataFrame,
    membership: dict[pd.Timestamp, set[str]],
    calendar: tuple[pd.Timestamp, ...],
    horizon: int,
) -> tuple[pd.DataFrame, pd.Series]:
    calendar_index = pd.DatetimeIndex(calendar)
    benchmark_return = (
        benchmark["close"].shift(-horizon) / benchmark["open"].shift(-1) - 1
    )
    labels: list[pd.DataFrame] = []
    closes: list[pd.Series] = []
    for instrument, frame in prices.groupby(level="instrument", sort=True):
        instrument_frame = frame.droplevel("instrument").reindex(calendar_index)
        raw_return = (
            instrument_frame["close"].shift(-horizon)
            / instrument_frame["open"].shift(-1)
            - 1
        )
        eligible = pd.Series(
            [instrument in membership[session] for session in calendar_index],
            index=calendar_index,
        )
        label = raw_return.where(eligible)
        labels.append(
            pd.DataFrame(
                {
                    "datetime": calendar_index,
                    "instrument": instrument,
                    "entry_date": pd.Series(calendar_index, index=calendar_index)
                    .shift(-1)
                    .to_numpy(),
                    "exit_date": pd.Series(calendar_index, index=calendar_index)
                    .shift(-horizon)
                    .to_numpy(),
                    "raw_return": raw_return.to_numpy(),
                    "benchmark_return": benchmark_return.to_numpy(),
                    "label": label.to_numpy(),
                    "eligible": eligible.to_numpy(),
                }
            )
        )
        close = instrument_frame["close"].copy()
        close.index = pd.MultiIndex.from_product(
            [calendar_index, [instrument]],
            names=["datetime", "instrument"],
        )
        closes.append(close)
    label_frame = (
        pd.concat(labels, ignore_index=True)
        .set_index(["datetime", "instrument"])
        .sort_index()
    )
    close_series = pd.concat(closes).sort_index().rename("close")
    return label_frame, close_series


def prepare_training_data(
    *,
    settings: Settings,
    export_dir: Path,
    experiment_dir: Path,
    export_run_id: uuid.UUID,
    momentum_lookback: int,
    horizon_sessions: int,
) -> PreparedTrainingData:
    dataset_path = experiment_dir / "training_dataset.parquet"
    metadata_path = experiment_dir / "candidate_metadata.parquet"
    if dataset_path.exists() and metadata_path.exists():
        combined = pd.read_parquet(dataset_path)
        metadata = pd.read_parquet(metadata_path)
        metadata["instrument_id"] = metadata["instrument_id"].map(uuid.UUID)
        metadata["issuer_id"] = metadata["issuer_id"].map(uuid.UUID)
        feature_columns = tuple(
            column for column in combined.columns if column.startswith("feature::")
        )
        features = combined[list(feature_columns)].rename(
            columns=lambda column: column.removeprefix("feature::")
        )
        labels = combined[
            [
                "entry_date",
                "exit_date",
                "raw_return",
                "benchmark_return",
                "label",
                "eligible",
            ]
        ]
        return PreparedTrainingData(
            features=features,
            labels=labels,
            momentum=combined["momentum"],
            metadata=metadata,
            feature_columns=tuple(features.columns),
        )

    provider = export_dir / "qlib_data"
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    calendar = tuple(
        pd.DatetimeIndex(
            pd.read_csv(provider / "calendars" / "day.txt", header=None)[0]
        ).sort_values()
    )
    feature_result = Alpha158FeatureService().compute_raw(
        provider_uri=provider,
        instruments="all",
        start_date=pd.Timestamp(manifest["calendar_start"]).date(),
        end_date=pd.Timestamp(manifest["calendar_end"]).date(),
    )
    features = normalize_alpha158_frame(feature_result.frame)
    repository = TrainingDataRepository(Database(settings))
    prices, benchmark, membership, metadata = repository.load(
        export_run_id=export_run_id,
        calendar=calendar,
    )
    labels, adjusted_close = _build_labels(
        prices=prices,
        benchmark=benchmark,
        membership=membership,
        calendar=calendar,
        horizon=horizon_sessions,
    )
    momentum = compute_momentum_scores(
        adjusted_close,
        lookback_sessions=momentum_lookback,
    ).rename("momentum")
    combined = features.rename(columns=lambda column: f"feature::{column}").join(
        labels,
        how="left",
    )
    combined = combined.join(momentum, how="left")
    experiment_dir.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(dataset_path)
    stored_metadata = metadata.copy()
    stored_metadata["instrument_id"] = stored_metadata["instrument_id"].astype(str)
    stored_metadata["issuer_id"] = stored_metadata["issuer_id"].astype(str)
    stored_metadata.to_parquet(metadata_path)
    return PreparedTrainingData(
        features=features,
        labels=labels,
        momentum=momentum,
        metadata=metadata,
        feature_columns=tuple(features.columns),
    )


def _segment_index(
    labels: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    fit_at: pd.Timestamp | None = None,
) -> pd.Index:
    dates = labels.index.get_level_values("datetime")
    label_exit = pd.to_datetime(labels["exit_date"])
    observation_end = min(end, fit_at) if fit_at is not None else end
    mask = (
        (dates >= start)
        & (dates <= end)
        & labels["label"].notna()
        & labels["exit_date"].notna()
        & (label_exit <= observation_end)
    )
    return labels.index[mask]


def _run_phase45_workflow(
    *,
    settings: Settings,
    export_dir: Path,
    model_config: VersionedConfig,
    label_config: VersionedConfig,
    selection_config: VersionedConfig | None,
    output_root: Path,
    persist_selection: bool,
) -> Phase45Summary | TrainingWorkflowSummary:
    if persist_selection != (selection_config is not None):
        raise ValueError(
            "selection_config is required exactly when production selection is persisted"
        )
    export_manifest = json.loads(
        (export_dir / "manifest.json").read_text(encoding="utf-8")
    )
    fit_at = pd.Timestamp(export_manifest["cutoff_at"])
    export_run_id = uuid.UUID(export_manifest["export_run_id"])
    experiment_identity = {
        "export_hash": export_manifest["content_hash"],
        "model_config_hash": model_config.config_hash,
        "label_config_hash": label_config.config_hash,
    }
    if selection_config is not None:
        experiment_identity["selection_config_hash"] = selection_config.config_hash
    experiment_key = _canonical_hash(experiment_identity)
    experiment_dir = Path(output_root) / experiment_key[:24]
    experiment_dir.mkdir(parents=True, exist_ok=True)
    model_payload = model_config.payload
    label_payload = label_config.payload
    horizon_sessions = int(label_payload["horizon_sessions"])
    if horizon_sessions < 1:
        raise ValueError("Label horizon must be positive")
    score_semantics = str(model_payload["prediction_semantics"])
    model_purpose = str(model_payload.get("model_purpose", "SHORT_5D"))
    return_policy = str(model_payload.get("return_policy", "PRICE_RETURN"))
    expected_score_semantics = f"PREDICTED_{horizon_sessions}D_RETURN"
    if score_semantics != expected_score_semantics:
        raise ValueError(
            "Model prediction_semantics must match the label horizon: "
            f"expected {expected_score_semantics}, got {score_semantics}"
        )
    baseline_config = model_payload["baselines"]
    if not isinstance(baseline_config, dict):
        raise ValueError("baselines config must be a mapping")
    data = prepare_training_data(
        settings=settings,
        export_dir=export_dir,
        experiment_dir=experiment_dir,
        export_run_id=export_run_id,
        momentum_lookback=int(baseline_config["momentum_lookback_sessions"]),
        horizon_sessions=horizon_sessions,
    )
    joined = data.labels.join(data.features, how="inner")
    valid = joined["label"].notna() & data.features.notna().any(axis=1)
    usable_dates = tuple(
        sorted(joined.index.get_level_values("datetime")[valid].unique())
    )
    fold_config = model_payload["walk_forward"]
    if not isinstance(fold_config, dict):
        raise ValueError("walk_forward config must be a mapping")
    if not bool(fold_config.get("purge_by_label_exit", True)):
        raise ValueError("walk_forward.purge_by_label_exit must remain enabled")
    folds = build_walk_forward_folds(
        usable_dates,
        WalkForwardSpec(
            minimum_train_sessions=int(fold_config["minimum_train_sessions"]),
            validation_sessions=int(fold_config["validation_sessions"]),
            test_sessions=int(fold_config["test_sessions"]),
            step_sessions=int(fold_config["step_sessions"]),
            minimum_test_sessions=int(fold_config["minimum_test_sessions"]),
        ),
    )
    lgb_parameters = model_payload["model"]
    if not isinstance(lgb_parameters, dict):
        raise ValueError("model config must be a mapping")
    evaluation_config = model_payload.get("evaluation", {})
    if not isinstance(evaluation_config, dict):
        raise ValueError("evaluation config must be a mapping")
    holding_period_sessions = int(
        evaluation_config.get("holding_period_sessions", horizon_sessions)
    )
    if holding_period_sessions != horizon_sessions:
        raise ValueError(
            "evaluation.holding_period_sessions must match the label horizon"
        )
    top_k_values = evaluation_config.get("top_k", [5, 10])
    if not isinstance(top_k_values, list) or not top_k_values:
        raise ValueError("evaluation.top_k must be a non-empty list")
    maximum_top_k = max(int(value) for value in top_k_values)
    prediction_rows: list[pd.DataFrame] = []
    for fold in folds:
        train_index = _segment_index(
            data.labels,
            start=fold.train_start,
            end=fold.train_end,
            fit_at=fold.test_start,
        ).intersection(data.features.index)
        valid_index = _segment_index(
            data.labels,
            start=fold.valid_start,
            end=fold.valid_end,
            fit_at=fold.test_start,
        ).intersection(data.features.index)
        test_index = _segment_index(
            data.labels,
            start=fold.test_start,
            end=fold.test_end,
            fit_at=fold.test_end,
        ).intersection(data.features.index)
        train_index = train_index[data.features.loc[train_index].notna().any(axis=1)]
        valid_index = valid_index[data.features.loc[valid_index].notna().any(axis=1)]
        test_index = test_index[data.features.loc[test_index].notna().any(axis=1)]

        ridge = RidgeBaseline(
            alpha=float(baseline_config["ridge_alpha"]),
            seed=int(model_payload["seed"]),
        )
        ridge.fit(data.features.loc[train_index], data.labels.loc[train_index, "label"])
        ridge_prediction = ridge.predict(data.features.loc[test_index])
        lightgbm = train_qlib_lightgbm(
            features=data.features,
            labels=data.labels["label"],
            train_index=train_index,
            valid_index=valid_index,
            parameters=lgb_parameters,
        )
        lgb_prediction = lightgbm.predict(data.features.loc[test_index])
        momentum_prediction = data.momentum.loc[test_index]
        for model_name, prediction in (
            ("momentum", momentum_prediction),
            ("ridge", ridge_prediction),
            ("lightgbm", lgb_prediction),
        ):
            frame = prediction.rename("score").to_frame().reset_index()
            frame["fold"] = fold.fold
            frame["model"] = model_name
            frame["label"] = data.labels.loc[prediction.index, "label"].to_numpy()
            prediction_rows.append(frame)

    predictions = dedupe_walk_forward_predictions(
        pd.concat(prediction_rows, ignore_index=True)
    )
    prediction_path = experiment_dir / "walk_forward_predictions.parquet"
    predictions.to_parquet(prediction_path, index=False)
    metrics: dict[str, dict[str, object]] = {}
    for model_name, frame in predictions.groupby("model"):
        indexed = frame.set_index(["datetime", "instrument"]).sort_index()
        metric = evaluate_predictions(
            indexed["score"],
            indexed["label"],
            top_k=maximum_top_k,
            min_cross_section=30,
            round_trip_cost_bps=float(
                evaluation_config.get("round_trip_cost_bps", 10)
            ),
            holding_period_sessions=holding_period_sessions,
        )
        fold_rank_ic = []
        for _, fold_frame in frame.groupby("fold"):
            fold_indexed = fold_frame.set_index(
                ["datetime", "instrument"]
            ).sort_index()
            fold_metric = evaluate_predictions(
                fold_indexed["score"],
                fold_indexed["label"],
                top_k=maximum_top_k,
                min_cross_section=30,
                round_trip_cost_bps=float(
                    evaluation_config.get("round_trip_cost_bps", 10)
                ),
                holding_period_sessions=holding_period_sessions,
            )
            fold_rank_ic.append(fold_metric.rank_ic_mean)
        model_metrics = asdict(metric)
        model_metrics["test_blocks"] = len(fold_rank_ic)
        model_metrics["fold_rank_ic_median"] = float(pd.Series(fold_rank_ic).median())
        metrics[str(model_name)] = model_metrics

    candidate_models = [
        model_name
        for model_name in ("lightgbm", "ridge")
        if model_name in metrics
        and float(metrics[model_name]["coverage"]) >= 0.8
        and int(metrics[model_name]["test_blocks"]) >= 3
    ]
    if not candidate_models:
        raise RuntimeError(
            "No candidate model passed temporal, test-block, and coverage eligibility"
        )
    selected_shadow_model = max(
        candidate_models,
        key=lambda model_name: (
            float(metrics[model_name]["rank_ic_mean"]),
            float(metrics[model_name]["fold_rank_ic_median"]),
            float(metrics[model_name]["net_top_10_return"]),
            float(metrics[model_name]["max_drawdown_top_10"]),
            model_name,
        ),
    )
    scorecard_quality_gate_passed = (
        float(metrics[selected_shadow_model]["rank_ic_mean"]) > 0
    )
    label_dates = data.labels.index.get_level_values("datetime")
    all_index = _segment_index(
        data.labels,
        start=pd.Timestamp(label_dates.min()),
        end=pd.Timestamp(export_manifest["calendar_end"]),
        fit_at=pd.Timestamp(export_manifest["calendar_end"]),
    ).intersection(data.features.index)
    all_index = all_index[data.features.loc[all_index].notna().any(axis=1)]
    all_dates = sorted(all_index.get_level_values("datetime").unique())
    final_valid_dates = set(all_dates[-int(fold_config["validation_sessions"]) :])
    final_valid_index = all_index[
        all_index.get_level_values("datetime").isin(final_valid_dates)
    ]
    final_train_index = all_index[
        ~all_index.get_level_values("datetime").isin(final_valid_dates)
    ]
    ridge_final = RidgeBaseline(
        alpha=float(baseline_config["ridge_alpha"]),
        seed=int(model_payload["seed"]),
    )
    ridge_final.fit(
        data.features.loc[all_index],
        data.labels.loc[all_index, "label"],
    )
    ridge_path = experiment_dir / "ridge.joblib"
    ridge_final.save(ridge_path)
    lightgbm_final = train_qlib_lightgbm(
        features=data.features,
        labels=data.labels["label"],
        train_index=final_train_index,
        valid_index=final_valid_index,
        parameters=lgb_parameters,
    )
    lightgbm_path = experiment_dir / "lightgbm.txt"
    lightgbm_final.save(lightgbm_path)
    momentum_path = experiment_dir / "momentum.json"
    momentum_path.write_text(
        json.dumps(
            {"lookback_sessions": baseline_config["momentum_lookback_sessions"]},
            indent=2,
        ),
        encoding="utf-8",
    )
    artifact_paths = {
        "momentum": momentum_path,
        "ridge": ridge_path,
        "lightgbm": lightgbm_path,
    }

    with Database(settings).connect() as connection, connection.transaction():
        export_row = connection.execute(
            """
            SELECT
                export.execution_context_id,
                export.universe_version_id,
                export.end_date,
                context.cutoff_at
            FROM analytics.qlib_export_run export
            JOIN ops.execution_context context
              ON context.execution_context_id = export.execution_context_id
            WHERE export.export_run_id = %s
            """,
            (export_run_id,),
        ).fetchone()
        if export_row is None:
            raise RuntimeError("Export run disappeared during training")
        registry = ModelRegistry(connection)
        effective_model_hash = _canonical_hash(
            {
                "model_config_hash": model_config.config_hash,
                "label_config_hash": label_config.config_hash,
            }
        )
        model_ids: dict[str, uuid.UUID] = {}
        for model_name, artifact_path in artifact_paths.items():
            model_ids[model_name] = registry.register(
                ModelRegistration(
                    model_name=model_name,
                    version=str(model_payload["version"]),
                    export_run_id=export_run_id,
                    config_hash=effective_model_hash,
                    split_spec={
                        "fit_at": fit_at.isoformat(),
                        "label_horizon_sessions": horizon_sessions,
                        "folds": [
                            {
                                key: value.isoformat()
                                if isinstance(value, pd.Timestamp)
                                else value
                                for key, value in asdict(fold).items()
                            }
                            | {
                                "fit_at": fold.test_start.isoformat(),
                                "label_observation_end": fold.valid_end.isoformat(),
                            }
                            for fold in folds
                        ],
                        "purge": "label_exit_within_segment",
                    },
                    parameters=(
                        dict(lgb_parameters)
                        if model_name == "lightgbm"
                        else dict(baseline_config)
                    ),
                    artifact_uri=artifact_path.resolve().as_uri(),
                    artifact_hash=_hash_file(artifact_path),
                    metrics=metrics[model_name],
                    promotion_status="SHADOW",
                    label_semantics=f"RAW_STOCK_{horizon_sessions}D_RETURN",
                    model_purpose=model_purpose,
                    return_policy=return_policy,
                )
            )

        if persist_selection:
            assert selection_config is not None
            latest_date = pd.Timestamp(export_row["end_date"])
            latest_index = data.features.index[
                data.features.index.get_level_values("datetime") == latest_date
            ]
            latest_features = data.features.loc[latest_index]
            if selected_shadow_model == "lightgbm":
                latest_prediction = lightgbm_final.predict(latest_features)
            elif selected_shadow_model == "ridge":
                latest_prediction = ridge_final.predict(latest_features)
            else:
                latest_prediction = data.momentum.loc[latest_index]
            eligible_metadata = data.metadata
            raw_scores: dict[uuid.UUID, float] = {}
            sectors: dict[uuid.UUID, str | None] = {}
            for (_, instrument), score in latest_prediction.dropna().items():
                if instrument not in eligible_metadata.index:
                    continue
                row = eligible_metadata.loc[instrument]
                instrument_id = row["instrument_id"]
                raw_scores[instrument_id] = float(score)
                sectors[instrument_id] = row["sector"]
            daily_scores = rank_daily_scores(
                session_date=latest_date.date(),
                raw_scores=raw_scores,
                sectors=sectors,
            )
            score_repository = ScoreRepository(connection)
            scoring_run_id = score_repository.create_run(
                session_date=latest_date.date(),
                execution_context_id=export_row["execution_context_id"],
                export_run_id=export_run_id,
                model_version_id=model_ids[selected_shadow_model],
                universe_version_id=export_row["universe_version_id"],
                config_hash=effective_model_hash,
                score_semantics=score_semantics,
                prediction_horizon_sessions=horizon_sessions,
            )
            score_repository.write_scores(
                scoring_run_id=scoring_run_id,
                scores=daily_scores,
                prediction_horizon=horizon_sessions,
            )
            selection_payload = selection_config.payload
            policy = SelectionPolicy(
                minimum_candidates=int(selection_payload["minimum_candidates"]),
                maximum_candidates=int(selection_payload["maximum_candidates"]),
                sector_cap=int(selection_payload["sector_cap"]),
                relaxed_sector_cap=int(selection_payload["relaxed_sector_cap"]),
            )
            candidate_metadata = {
                row["instrument_id"]: CandidateMetadata(
                    instrument_id=row["instrument_id"],
                    issuer_id=row["issuer_id"],
                    symbol=str(row["symbol"]),
                    sector=row["sector"],
                )
                for _, row in eligible_metadata.iterrows()
            }
            selection_result = select_candidates(
                scores=daily_scores,
                metadata=candidate_metadata,
                policy=policy,
            )
            generated_at = datetime.now(UTC)
            selection_run_id = SelectionRepository(connection).persist(
                price_session_date=latest_date.date(),
                cutoff_at=export_row["cutoff_at"],
                generated_at=generated_at,
                valid_until=None,
                scoring_run_id=scoring_run_id,
                policy_version=str(selection_payload["version"]),
                requested_count=policy.maximum_candidates,
                result=selection_result,
            )

    metrics_path = experiment_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "experiment_key": experiment_key,
                "selected_shadow_model": selected_shadow_model,
                "promotion_gate_passed": False,
                "scorecard_quality_gate_passed": scorecard_quality_gate_passed,
                "model_purpose": model_purpose,
                "prediction_horizon_sessions": horizon_sessions,
                "return_policy": return_policy,
                "label_name": label_config.name,
                "label_version": label_config.version,
                "label_config_hash": label_config.config_hash,
                "metrics": metrics,
                "model_version_ids": {
                    name: str(value) for name, value in model_ids.items()
                },
            },
            default=str,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    if not persist_selection:
        return TrainingWorkflowSummary(
            experiment_key=experiment_key,
            experiment_dir=experiment_dir,
            export_run_id=export_run_id,
            model_version_id=model_ids[selected_shadow_model],
            selected_shadow_model=selected_shadow_model,
            metrics=metrics,
            model_purpose=model_purpose,
            prediction_horizon_sessions=horizon_sessions,
            return_policy=return_policy,
            scorecard_quality_gate_passed=scorecard_quality_gate_passed,
        )

    payload = candidate_result_payload(
        selection_run_id=selection_run_id,
        scoring_run_id=scoring_run_id,
        model_version_id=model_ids[selected_shadow_model],
        execution_context_id=export_row["execution_context_id"],
        price_session_date=latest_date.date(),
        cutoff_at=export_row["cutoff_at"],
        generated_at=generated_at,
        policy_version=str(selection_payload["version"]),
        result=selection_result,
        model_purpose=model_purpose,
        prediction_horizon_sessions=horizon_sessions,
        return_policy=return_policy,
        promotion_status="SHADOW",
        model_status="SHADOW",
        promotion_gate_passed=False,
    )
    candidate_dir = experiment_dir / "candidates"
    candidate_dir.mkdir(exist_ok=True)
    candidate_path = candidate_dir / f"{latest_date.date()}-{selection_run_id}.json"
    candidate_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return Phase45Summary(
        experiment_key=experiment_key,
        experiment_dir=experiment_dir,
        export_run_id=export_run_id,
        model_version_id=model_ids[selected_shadow_model],
        scoring_run_id=scoring_run_id,
        selection_run_id=selection_run_id,
        selected_shadow_model=selected_shadow_model,
        promotion_gate_passed=False,
        metrics=metrics,
        candidate_path=candidate_path,
        candidate_count=len(selection_result.candidates),
        price_session_date=latest_date.date(),
        model_purpose=model_purpose,
        prediction_horizon_sessions=horizon_sessions,
        return_policy=return_policy,
        scorecard_quality_gate_passed=scorecard_quality_gate_passed,
    )


def run_phase45_workflow(
    *,
    settings: Settings,
    export_dir: Path,
    model_config: VersionedConfig,
    label_config: VersionedConfig,
    selection_config: VersionedConfig,
    output_root: Path,
) -> Phase45Summary:
    summary = _run_phase45_workflow(
        settings=settings,
        export_dir=export_dir,
        model_config=model_config,
        label_config=label_config,
        selection_config=selection_config,
        output_root=output_root,
        persist_selection=True,
    )
    if not isinstance(summary, Phase45Summary):
        raise RuntimeError("DAILY phase45 workflow did not persist selection")
    return summary


def run_training_only_workflow(
    *,
    settings: Settings,
    export_dir: Path,
    model_config: VersionedConfig,
    label_config: VersionedConfig,
    output_root: Path,
) -> TrainingWorkflowSummary:
    summary = _run_phase45_workflow(
        settings=settings,
        export_dir=export_dir,
        model_config=model_config,
        label_config=label_config,
        selection_config=None,
        output_root=output_root,
        persist_selection=False,
    )
    if not isinstance(summary, TrainingWorkflowSummary):
        raise RuntimeError("Training-only workflow attempted production selection")
    return summary
