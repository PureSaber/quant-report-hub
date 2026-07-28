"""Command-line entry for quant-report-hub."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quant_report_hub.config import VizConfig, plot_groups_for
from quant_report_hub.context import CompareContext, PlotContext
from quant_report_hub.plots.registry import run_compare, run_plots


def _parse_strategy_params(raw: str | None) -> dict[str, float]:
    if not raw:
        return {}
    out: dict[str, float] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = float(v.strip())
    return out


def _cmd_run(args: argparse.Namespace) -> int:
    groups = plot_groups_for(args.adapter)
    plot_ids = groups.get(args.plots, groups["all"])
    cfg = VizConfig(
        output_root=args.output_root,
        run_id=args.run_id,
        out_dir=args.out_dir or str(Path("reports") / args.run_id),
        adapter=args.adapter,
        market_root=args.market_root or "",
        years=list(args.years or []),
        strategy_params=_parse_strategy_params(args.strategy_params),
        top_n=args.top_n,
    )
    ctx = PlotContext.from_run(
        cfg,
        adapter=args.adapter,
        strategy=args.strategy,
        initial_capital=args.initial_capital,
    )
    if ctx.portfolio.empty:
        print(f"warning: {args.run_id} has no portfolio data", file=sys.stderr)
    outputs = run_plots(ctx, plot_ids)
    print(f"generated {len(outputs)} files -> {ctx.out_dir}")
    for p in outputs:
        print(f"  {p.name}")
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    if len(args.run_ids) < 2:
        print("compare requires at least 2 run-id values", file=sys.stderr)
        return 1
    cfg = VizConfig(
        output_root=args.output_root,
        run_id=args.run_ids[0],
        out_dir=args.out_dir or str(Path("reports") / "compare"),
        adapter=args.adapter,
    )
    runs = [
        PlotContext.from_run(cfg, rid, adapter=args.adapter, strategy=args.strategy)
        for rid in args.run_ids
    ]
    cmp = CompareContext(cfg=cfg, runs=runs, out_dir=Path(cfg.out_dir))
    cmp.out_dir.mkdir(parents=True, exist_ok=True)
    outputs = run_compare(cmp)
    print(f"generated {len(outputs)} compare plots -> {cmp.out_dir}")
    for p in outputs:
        print(f"  {p.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quant-report", description="Quant research output visualization hub")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Generate charts for one run")
    run.add_argument("--adapter", default="spread", choices=["spread", "equity"])
    run.add_argument("--output-root", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--out-dir", default="")
    run.add_argument("--strategy", default="")
    run.add_argument("--initial-capital", type=float, default=10000.0)
    run.add_argument("--market-root", default="")
    run.add_argument("--years", nargs="*", default=[])
    run.add_argument("--strategy-params", default="")
    run.add_argument("--plots", default="all")
    run.add_argument("--top-n", type=int, default=10)
    run.set_defaults(func=_cmd_run)

    cmp = sub.add_parser("compare", help="Compare multiple runs (plot 14)")
    cmp.add_argument("--adapter", default="spread", choices=["spread", "equity"])
    cmp.add_argument("--output-root", required=True)
    cmp.add_argument("--run-ids", nargs="+", required=True)
    cmp.add_argument("--out-dir", default="")
    cmp.add_argument("--strategy", default="")
    cmp.set_defaults(func=_cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        groups = plot_groups_for(args.adapter)
        if args.plots not in groups:
            print(f"plots must be one of {list(groups.keys())}", file=sys.stderr)
            return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
