"""quant_report_hub/plots/style.py —  matplotlib 样式。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Protocol

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


class _PlotOutCtx(Protocol):
    out_dir: Path

    @property
    def cfg(self) -> Any: ...


_CJK_FONT_CANDIDATES = (
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
)


def _resolve_cjk_font() -> str:
    """Pick the first installed CJK font; fall back to sans-serif."""
    available = {font.name for font in fm.fontManager.ttflist}
    candidates = _CJK_FONT_CANDIDATES
    if sys.platform.startswith("win"):
        candidates = ("Microsoft YaHei", "Microsoft YaHei UI", "SimHei") + candidates
    for name in candidates:
        if name in available:
            return name
    return "sans-serif"


def _configure_cjk_font(font_name: str) -> None:
    """Apply CJK font after seaborn theme setup (set_theme resets sans-serif)."""
    plt.rcParams["font.family"] = font_name
    plt.rcParams["font.sans-serif"] = [font_name] + [
        name for name in plt.rcParams.get("font.sans-serif", []) if name != font_name
    ]
    plt.rcParams["axes.unicode_minus"] = False


def apply_style() -> None:
    font_name = _resolve_cjk_font()
    # set_theme must run first; pass font= so seaborn does not fall back to Arial.
    sns.set_theme(
        style="whitegrid",
        context="notebook",
        font_scale=0.95,
        font=font_name,
    )
    _configure_cjk_font(font_name)
    plt.rcParams.update(
        {
            "figure.dpi": 100,
            "savefig.bbox": "tight",
            "axes.titlesize": 12,
            "axes.labelsize": 10,
        }
    )


def save_fig(path, dpi: int = 120) -> str:
    plt.savefig(path, dpi=dpi)
    plt.close()
    return str(path)


def prepare_plot(*checks: pd.DataFrame | pd.Series | None, require_all: bool = True) -> bool:
    """Apply plot style when empty checks pass; return False to skip rendering."""
    if not checks:
        apply_style()
        return True
    empties = [check is None or (hasattr(check, "empty") and check.empty) for check in checks]
    if require_all and any(empties):
        return False
    if not require_all and all(empties):
        return False
    apply_style()
    return True


def save_ctx_plot(ctx: _PlotOutCtx, filename: str | Path) -> Path:
    """Save the active figure under ctx.out_dir at ctx.cfg.dpi."""
    path = ctx.out_dir / filename if isinstance(filename, str) else filename
    return Path(save_fig(path, ctx.cfg.dpi))


POS = "#2ca02c"
NEG = "#d62728"
NEU = "#1f77b4"
