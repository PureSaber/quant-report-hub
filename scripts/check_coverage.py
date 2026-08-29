"""Fail CI when overall or attribution/reconciliation/report branch coverage regresses."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MINIMUM_TOTAL = 80.0
MINIMUM_CORE_BRANCH = 90.0
CORE_MODULES = ("quant_report_hub/attribution.py",)


def _percentage(numerator: int, denominator: int) -> float:
    return 100.0 if denominator == 0 else 100.0 * numerator / denominator


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(f"usage: {argv[0]} COVERAGE_JSON")
    report = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    total = float(report["totals"]["percent_covered"])
    if total < MINIMUM_TOTAL:
        raise SystemExit(f"全仓覆盖率{total:.2f}%低于{MINIMUM_TOTAL:.0f}%")
    failures: list[str] = []
    files = {path.replace("\\", "/"): value for path, value in report["files"].items()}
    for module in CORE_MODULES:
        summary = files.get(module, {}).get("summary")
        if summary is None:
            failures.append(f"核心模块未出现在覆盖报告中: {module}")
            continue
        branches = int(summary["num_branches"])
        covered = int(summary["covered_branches"])
        percentage = _percentage(covered, branches)
        if branches == 0 or percentage < MINIMUM_CORE_BRANCH:
            failures.append(
                f"{module}纯分支覆盖率{covered}/{branches}={percentage:.2f}%"
                f"低于{MINIMUM_CORE_BRANCH:.0f}%"
            )
        else:
            print(f"{module}: pure branch coverage {covered}/{branches}={percentage:.2f}%")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"total coverage: {total:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
