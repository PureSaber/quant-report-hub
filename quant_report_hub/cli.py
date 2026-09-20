"""Command-line entry for quant-report-hub."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

from quant_report_hub.attribution import attribute_standard_run, reconcile_standard_run_v2
from quant_report_hub.config import VizConfig, plot_groups_for
from quant_report_hub.context import CompareContext, PlotContext
from quant_report_hub.dashboard import write_dashboard_bundle
from quant_report_hub.dashboard_exports import write_daily_package, write_runtime_sidecars
from quant_report_hub.dashboard_server import serve_dashboard
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


def _cmd_attribute(args: argparse.Namespace) -> int:
    asset_returns = pd.read_csv(args.asset_returns)
    factor_returns = pd.read_csv(args.factor_returns) if args.factor_returns else None
    benchmark = pd.read_csv(args.benchmark_positions) if args.benchmark_positions else None
    classifications = pd.read_csv(args.classifications) if args.classifications else None
    manifest = attribute_standard_run(
        args.run_dir,
        asset_returns,
        factor_returns=factor_returns,
        benchmark_positions=benchmark,
        classifications=classifications,
        out_dir=args.out_dir or None,
        allow_same_day_positions=args.allow_same_day_positions,
    )
    destination = Path(args.out_dir) if args.out_dir else Path(args.run_dir) / "attribution"
    print(f"generated {len(manifest.files)} attribution files -> {destination}")
    return 0


def _cmd_reconcile_v2(args: argparse.Namespace) -> int:
    references = pd.read_csv(args.slippage_references) if args.slippage_references else None
    manifest = reconcile_standard_run_v2(
        args.run_dir,
        out_dir=args.out_dir or None,
        slippage_references=references,
    )
    destination = (
        Path(args.out_dir) if args.out_dir else Path(args.run_dir) / "reports" / "attribution-v2"
    )
    print(f"reconciled {sum(manifest.row_counts.values())} rows from standard/v2 -> {destination}")
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    try:
        destination, snapshot = write_dashboard_bundle(
            [Path(root) for root in args.decision_root],
            Path(args.out),
            db=Path(args.lab_db) if args.lab_db else None,
        )
        sidecars = write_runtime_sidecars(snapshot, destination)
    except (OSError, ValueError) as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 1
    print(f"generated research dashboard -> {destination}")
    print(f"generated alert/status sidecars -> {', '.join(path.name for path in sidecars)}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    if args.poll_seconds <= 0 or not 0 < args.port < 65536:
        print("serve: poll-seconds and port must be positive", file=sys.stderr)
        return 1
    try:
        serve_dashboard(
            [Path(root) for root in args.decision_root],
            Path(args.out),
            db=Path(args.lab_db) if args.lab_db else None,
            host=args.host,
            port=args.port,
            poll_seconds=args.poll_seconds,
            serve_root=Path(args.serve_root) if args.serve_root else None,
        )
    except (OSError, ValueError) as exc:
        print(f"serve: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_daily_package(args: argparse.Namespace) -> int:
    roots = [Path(root) for root in args.decision_root]
    out_dir = Path(args.out_dir)
    try:
        _, snapshot = write_dashboard_bundle(
            roots,
            out_dir / "index.html",
            db=Path(args.lab_db) if args.lab_db else None,
        )
        outputs = write_daily_package(
            snapshot,
            out_dir,
            browser=Path(args.browser) if args.browser else None,
            include_pdf=not args.no_pdf,
        )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"daily-package: {exc}", file=sys.stderr)
        return 1
    print(f"generated daily package ({len(outputs)} files) -> {out_dir.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="quant-report", description="Quant research output visualization hub"
    )
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

    attribution = sub.add_parser("attribute", help="Attribute a standard research run")
    attribution.add_argument("--run-dir", required=True)
    attribution.add_argument("--asset-returns", required=True)
    attribution.add_argument("--factor-returns", default="")
    attribution.add_argument("--benchmark-positions", default="")
    attribution.add_argument("--classifications", default="")
    attribution.add_argument("--out-dir", default="")
    attribution.add_argument("--allow-same-day-positions", action="store_true")
    attribution.set_defaults(func=_cmd_attribute)

    reconcile = sub.add_parser(
        "reconcile-v2",
        help="严格加载standard/v2并发布跨资产精确归因报告",
    )
    reconcile.add_argument("--run-dir", required=True)
    reconcile.add_argument("--out-dir", default="")
    reconcile.add_argument(
        "--slippage-references",
        default="",
        help="包含因果reference价格、可得时间、乘数及FX的CSV；存在slippage成本时必填",
    )
    reconcile.set_defaults(func=_cmd_reconcile_v2)

    dashboard = sub.add_parser("dashboard", help="生成决策、实验与证据统一研究看板")
    dashboard.add_argument(
        "--decision-root",
        action="append",
        required=True,
        help="包含 latest.json 和运行子目录的路径；可重复指定多个目录",
    )
    dashboard.add_argument("--lab-db", default="", help="只读 quant-lab SQLite 实验索引")
    dashboard.add_argument("--out", default="reports/dashboard.html", help="源目录之外的 HTML 文件")
    dashboard.set_defaults(func=_cmd_dashboard)

    serve = sub.add_parser("serve", help="生成、监视并在本机持续提供研究看板")
    serve.add_argument(
        "--decision-root",
        action="append",
        required=True,
        help="包含 latest.json 和运行子目录的路径；可重复指定多个目录",
    )
    serve.add_argument("--lab-db", default="", help="只读 quant-lab SQLite 实验索引")
    serve.add_argument("--out", default="reports/dashboard.html", help="源目录之外的 HTML 文件")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8767)
    serve.add_argument("--poll-seconds", type=float, default=2.0)
    serve.add_argument("--serve-root", default="", help="HTTP 根目录；默认取输入和输出的共同父目录")
    serve.set_defaults(func=_cmd_serve)

    package = sub.add_parser("daily-package", help="导出 HTML、PDF、CSV 和异常清单日报包")
    package.add_argument(
        "--decision-root",
        action="append",
        required=True,
        help="包含 latest.json 和运行子目录的路径；可重复指定多个目录",
    )
    package.add_argument("--lab-db", default="", help="只读 quant-lab SQLite 实验索引")
    package.add_argument("--out-dir", required=True, help="源目录之外的日报包目录")
    package.add_argument("--browser", default="", help="用于打印 PDF 的 Edge/Chromium 可执行文件")
    package.add_argument("--no-pdf", action="store_true", help="仅在无浏览器的自动化环境跳过 PDF")
    package.set_defaults(func=_cmd_daily_package)
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
