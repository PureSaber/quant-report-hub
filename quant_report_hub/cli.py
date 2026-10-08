"""Command-line entry for quant-report-hub."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from quant_report_hub.attribution import attribute_standard_run, reconcile_standard_run_v2
from quant_report_hub.cash_attribution import reconcile_cash_ledger_v2
from quant_report_hub.cash_price_bridge import verify_cash_price_bridge, write_cash_price_bridge
from quant_report_hub.config import VizConfig, plot_groups_for
from quant_report_hub.context import CompareContext, PlotContext
from quant_report_hub.dashboard import write_dashboard_bundle
from quant_report_hub.dashboard_exports import write_daily_package, write_runtime_sidecars
from quant_report_hub.dashboard_server import serve_dashboard
from quant_report_hub.execution_diagnostics import (
    verify_execution_diagnostics,
    write_execution_diagnostics,
)
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


def _cmd_source_resolution(args: argparse.Namespace) -> int:
    from quant_report_hub.source_reconciliation import resolution_card

    print(json.dumps(resolution_card(args.decision), ensure_ascii=False, indent=2))
    return 0


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
        cost_unit=args.cost_unit,
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


def _cmd_cash_attribution(args: argparse.Namespace) -> int:
    try:
        manifest = reconcile_cash_ledger_v2(args.run_dir, out_dir=args.out_dir)
    except (OSError, ValueError) as exc:
        print(f"cash-attribution: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _cmd_cash_price_bridge(args: argparse.Namespace) -> int:
    try:
        common = {"references": args.references, "references_sha256": args.references_sha256}
        if args.command == "verify-cash-price-bridge":
            receipt = verify_cash_price_bridge(
                args.run_dir,
                **common,
                report_dir=args.report_dir,
                manifest_sha256=args.manifest_sha256,
            )
        else:
            receipt = write_cash_price_bridge(args.run_dir, **common, out_dir=args.out_dir)
    except (OSError, ValueError) as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    try:
        destination, snapshot = write_dashboard_bundle(
            [Path(root) for root in args.decision_root],
            Path(args.out),
            db=Path(args.lab_db) if args.lab_db else None,
            paired_evidence=[(Path(p), sha) for p, sha in args.paired_evidence],
        )
        sidecars = write_runtime_sidecars(snapshot, destination)
    except (OSError, ValueError) as exc:
        print(f"dashboard: {exc}", file=sys.stderr)
        return 1
    print(f"generated research dashboard -> {destination}")
    print(f"generated alert/status sidecars -> {', '.join(path.name for path in sidecars)}")
    return 0


def _cmd_execution_diagnostics(args: argparse.Namespace) -> int:
    try:
        common = {
            "references": args.references,
            "references_sha256": args.references_sha256,
            "policy": args.policy,
            "policy_sha256": args.policy_sha256,
        }
        if args.command == "verify-execution-cost-diagnostics":
            receipt = verify_execution_diagnostics(
                args.run_dir,
                **common,
                report_dir=args.report_dir,
                manifest_sha256=args.manifest_sha256,
            )
        else:
            receipt = write_execution_diagnostics(args.run_dir, **common, out_dir=args.out_dir)
    except (OSError, ValueError) as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["summary"]["status"] == "computed" else 2


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
            paired_evidence=[(Path(p), sha) for p, sha in args.paired_evidence],
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
            paired_evidence=[(Path(p), sha) for p, sha in args.paired_evidence],
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
    attribution.add_argument("--cost-unit", choices=["currency", "return"], default=None)
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

    cash = sub.add_parser("cash-attribution", help="从原生现金证券账本重建期间损益和分红应收")
    cash.add_argument("--run-dir", required=True)
    cash.add_argument("--out-dir", required=True, help="尚不存在且位于源运行目录之外的报告目录")
    cash.set_defaults(func=_cmd_cash_attribution)

    for command in ("cash-price-bridge", "verify-cash-price-bridge"):
        bridge = sub.add_parser(
            command, help="独立订单接受时报价与原生现金账本的有符号成交价差对账"
        )
        bridge.add_argument("--run-dir", required=True)
        bridge.add_argument(
            "--references", required=True, help="独立报价包清单；同目录含quotes.csv"
        )
        bridge.add_argument("--references-sha256", required=True, help="事先绑定的报价清单SHA-256")
        if command.startswith("verify-"):
            bridge.add_argument("--report-dir", required=True)
            bridge.add_argument("--manifest-sha256", required=True, help="已保存的报告清单SHA-256")
        else:
            bridge.add_argument("--out-dir", required=True, help="来源之外尚不存在的报告目录")
        bridge.set_defaults(func=_cmd_cash_price_bridge)

    for command in ("execution-cost-diagnostics", "verify-execution-cost-diagnostics"):
        diagnostics = sub.add_parser(command, help="按训练及留出期诊断有符号成交价差，不修改账本")
        diagnostics.add_argument("--run-dir", required=True)
        diagnostics.add_argument("--references", required=True)
        diagnostics.add_argument("--references-sha256", required=True)
        diagnostics.add_argument("--policy", required=True)
        diagnostics.add_argument("--policy-sha256", required=True)
        if command.startswith("verify-"):
            diagnostics.add_argument("--report-dir", required=True)
            diagnostics.add_argument("--manifest-sha256", required=True)
        else:
            diagnostics.add_argument("--out-dir", required=True)
        diagnostics.set_defaults(func=_cmd_execution_diagnostics)

    dashboard = sub.add_parser("dashboard", help="生成决策、实验与证据统一研究看板")
    dashboard.add_argument(
        "--decision-root",
        action="append",
        default=[],
        help="包含 latest.json 和运行子目录的路径；可重复指定多个目录",
    )
    dashboard.add_argument("--lab-db", default="", help="只读 quant-lab SQLite 实验索引")
    dashboard.add_argument("--out", default="reports/dashboard.html", help="源目录之外的 HTML 文件")
    dashboard.set_defaults(func=_cmd_dashboard)

    serve = sub.add_parser("serve", help="生成、监视并在本机持续提供研究看板")
    serve.add_argument(
        "--decision-root",
        action="append",
        default=[],
        help="包含 latest.json 和运行子目录的路径；可重复指定多个目录",
    )
    serve.add_argument("--lab-db", default="", help="只读 quant-lab SQLite 实验索引")
    serve.add_argument("--out", default="reports/dashboard.html", help="源目录之外的 HTML 文件")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8767)
    serve.add_argument("--poll-seconds", type=float, default=2.0)
    serve.add_argument(
        "--serve-root", default="", help="URL路径基准；仅开放看板、状态和明确列出的证据文件"
    )
    serve.set_defaults(func=_cmd_serve)

    package = sub.add_parser("daily-package", help="导出 HTML、PDF、CSV 和异常清单日报包")
    package.add_argument(
        "--decision-root",
        action="append",
        default=[],
        help="包含 latest.json 和运行子目录的路径；可重复指定多个目录",
    )
    package.add_argument("--lab-db", default="", help="只读 quant-lab SQLite 实验索引")
    package.add_argument("--out-dir", required=True, help="源目录之外的日报包目录")
    package.add_argument("--browser", default="", help="用于打印 PDF 的 Edge/Chromium 可执行文件")
    package.add_argument("--no-pdf", action="store_true", help="仅在无浏览器的自动化环境跳过 PDF")
    package.set_defaults(func=_cmd_daily_package)
    for command in (dashboard, serve, package):
        command.add_argument(
            "--paired-evidence",
            nargs=2,
            action="append",
            default=[],
            metavar=("JSON", "SHA256"),
            help="已固定哈希的paired-evidence.json；重复指定各测试折，保留失败折并核验原生账本",
        )
    source = sub.add_parser("source-resolution", help="核验来源裁决并列出需要重跑的产物")
    source.add_argument("--decision", required=True)
    source.set_defaults(func=_cmd_source_resolution)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {"dashboard", "serve", "daily-package"} and not (
        args.decision_root or args.lab_db or args.paired_evidence
    ):
        parser.error("至少指定决策目录、实验索引或配对研究证据")
    if args.command == "run":
        groups = plot_groups_for(args.adapter)
        if args.plots not in groups:
            print(f"plots must be one of {list(groups.keys())}", file=sys.stderr)
            return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
