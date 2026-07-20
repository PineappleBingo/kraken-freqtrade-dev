"""CLI: turn a lab run directory of freqtrade exports into a comparison report.

    python -m companion.backtest_lab.cli <run_dir> -o <out_dir> [--label text]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .metrics import analyze, best_per_metric
from .render import write_report
from .results import load_results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path,
                        help="directory with freqtrade backtest exports")
    parser.add_argument("-o", "--out-dir", type=Path, required=True,
                        help="where to write compare_<ts>.html / latest.html")
    parser.add_argument("--label", default="",
                        help="short label shown in the report header")
    args = parser.parse_args(argv)

    results = load_results(args.run_dir)
    analyses = [analyze(r) for r in results]
    winners = best_per_metric(analyses)
    label = args.label or args.run_dir.name

    path = write_report(analyses, winners, args.out_dir, run_label=label)

    print(f"Compared {len(analyses)} strategies:")
    for a in analyses:
        metrics = a["metrics"]
        print(f"  {a['name']:<28} net {metrics['Net profit %']}%  "
              f"win {metrics['Win rate %']}%  "
              f"maxDD {metrics['Max drawdown %']}%  "
              f"trades {metrics['Trades']}")
    print(f"Report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
