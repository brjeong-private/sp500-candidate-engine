from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from sp500_candidate_engine.analytics.features import Alpha158FeatureService


def _date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    args = parser.parse_args()

    result = Alpha158FeatureService().compute_raw(
        provider_uri=args.provider_uri,
        instruments="all",
        start_date=args.start,
        end_date=args.end,
    )
    values = result.frame.to_numpy(dtype=float)
    print(
        json.dumps(
            {
                "rows": len(result.frame),
                "columns": result.frame.shape[1],
                "infinite": int(np.isinf(values).sum()),
                "nan": int(np.isnan(values).sum()),
                "first_index": str(result.frame.index[0]),
                "last_index": str(result.frame.index[-1]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
