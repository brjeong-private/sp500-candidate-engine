from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import date
from pathlib import Path

from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.llm_preselection.pipeline import run_llm_preselection


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the independent LLM Top 20 pipeline")
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--execution-context-id", type=uuid.UUID, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    summary = asyncio.run(
        run_llm_preselection(
            Settings.from_env(args.env_file),
            target_session=args.date,
            execution_context_id=args.execution_context_id,
            repository_root=Path(__file__).parents[3],
        )
    )
    print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
    if summary.status != "SUCCEEDED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
