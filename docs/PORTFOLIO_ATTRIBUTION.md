# Cross-asset portfolio accounting and risk attribution

```bash
python -m quant_report_hub.portfolio_attribution --input examples/portfolio_attribution.json --out reports/portfolio
python -m quant_report_hub.portfolio_attribution --input examples/portfolio_attribution.json --out reports/portfolio --verify
```

The first command creates a new report directory with `report.html`, `result.json`,
`components.csv`, the exact `input.json` snapshot and a hash manifest. The second reloads and revalidates the original
sources, recomputes all outputs, and compares exact bytes. It does not merely trust the
report's own hash list. Native source directories cannot be report destinations.
`evaluate_portfolio_attribution(spec, source_root=...)` is the pure evaluation API.

## Evidence boundaries and adapters

Input schema is `quant-report-hub.portfolio-attribution/v1`. Each account has unique `id`
and `economic_scope`, currency, asset-class label, source reference, explicit data nature,
an evidence level, and a complete ordered list of exact periods. Economic scopes must
represent disjoint invested capital: do not sum alternative backtests, a fund and its
look-through constituents, or two reports of the same account. Source identity duplicate
checks cannot establish this economic disjointness independently.

| Evidence level | What is established |
|---|---|
| `nav_bridge` | External opening/closing NAV and flows; all local P&L remains residual |
| `reported_components` | Producer-declared signed local components and separately computed residual |
| `native_cash_ledger` | Full existing immutable `standard/v2` cash-ledger reconstruction, unchanged scope |
| `validated_v2_components` | Existing M5 cost/component/traceability/NAV reconciliation, unchanged scope |

The first two adapt normalized results from any asset class, including funds, futures,
FX, bonds, options and swaps. Their class labels do not certify native lifecycle rules.
They require explicit accounting summaries and do not infer transactions from NAV.
Lifecycle-specific producers under development can emit these external interfaces;
this change neither rewrites nor certifies those producers.

Both native adapters take `run_dir` (relative to the input JSON), caller-pinned
`run_manifest_sha256`, and caller-supplied period/FX/publication metadata. Caller-supplied
NAV, flows and components are ignored for native inputs; amounts are rederived from the
validated source. Native report `known_at` cannot predate the run's actual `created_at`.

The cash adapter calls the existing `_reconstruct` after full hash/schema/lineage
validation. It includes first-period costs, corporate entitlements and payments. It
accepts every original source return period, with the first opening timestamp explicitly
supplied at or before the first ledger event. Its zero residual does not imply causal
execution-price or impact attribution.

The M5 adapter calls the same read-only reconstruction used by `reconcile-v2`; publication
was separated from calculation without changing the existing financial checks. It
requires a single source account and all adjacent portfolio snapshot intervals. Source
price/carry/roll/FX components stay producer-supplied; commission, tax, funding, maker,
taker, slippage and other costs keep their existing evidence checks and signed values.
Optional `slippage_references` requires `slippage_references_sha256` and must pass the
original causal reference checks. Source `residual` stays visible as `source_residual`;
any further NAV difference remains `residual`. Neither residual is called alpha.

## Common-period, cash and currency contract

Every account must have the identical nonempty start/end sequence. Periods are contiguous,
and local opening NAV and starting FX must equal the preceding closing amounts exactly.
No interpolation, stale-account carry-forward or missing-account zero filling is used.

Each external period supplies decimal-string `opening_nav`, `closing_nav`, `fx_start`,
`fx_end`, `components` (signed local-currency P&L) and `flows`. All timestamps are explicit
and timezone-aware; end, `known_at`, and both FX availability times must be mature by
`evaluation_as_of`. FX is reporting-base currency per local currency. Base-currency
accounts and flows require FX equal to one. Cash is an explicit account/sleeve and can
report `cash_interest`; unreported cash income remains residual.

Flows contain unique-per-account `flow_id`, signed local `amount`, `time`, `known_at`, `fx_rate`, `fx_known_at`, and
`kind=external` or `internal_transfer`. Internal transfers also require a `transfer_id`.
Exactly two different accounts must report equal and opposite base values at the same
timestamp. Internal transfers cancel at the portfolio level; unmatched transfers fail.
Positive flows are contributions to an account, negative flows are withdrawals. Dividends
and financing income are P&L, not external capital.

For local NAV V, local flows F_j and base/local FX X:

* local P&L = `V1 - V0 - sum(F_j)`;
* local residual = local P&L minus the supplied signed components;
* each component and residual translates at `X1`;
* opening-capital FX = `V0*(X1-X0)`;
* flow-timing FX = `sum(F_j*(X1-X_j))`;
* total base P&L = `V1*X1 - V0*X0 - sum(F_j*X_j)`.

This exact Decimal bridge retains the local-return/FX cross term in closing-FX-translated
local P&L. No invented reference prices, hedge returns or cash opportunity costs appear.
All amounts are summed before ratios. `pnl_over_opening_nav` and account contributions
are explicitly **not TWR** when any capital flows occurred, including offsetting flows
whose net is zero. Zero or negative total opening capital makes those ratios unavailable.

## Optional risk attribution

`risk_models` can supply one covariance snapshot per period start, with exact ordered
account axes, `return_basis=base_net_simple_total_return`, `period_unit`, source reference,
estimation-end time and known-at time. Both must precede the forecast period. The matrix
must be finite, symmetric and PSD. Opening base NAV determines weights; Euler component
variance is `w_i(Σw)_i`. Components sum to portfolio variance; dividing by portfolio
volatility gives volatility contributions. Missing models are `unavailable`, not zero
risk. This is a model-based ex-ante decomposition, not causal asset/strategy performance.

## Independent checks and limits

The bundled synthetic EUR case has local NAV 100→130, a 20 EUR contribution at FX 1.2,
and endpoint FX 1.1→1.3. Local P&L 10 becomes 13 USD, opening FX contributes 20 USD and
flow FX contributes 2 USD, totaling 35 USD. Adding USD cash interest +1 and a fund NAV
residual -1 leaves portfolio P&L 35, exactly `239 - 180 - 24`. Tests independently check
this identity, paired internal transfers, zero-net-flow semantics and the Euler formula.
Existing cash, futures and crypto fixture paths are revalidated through their original
accounting code. Broken source hashes and future references fail instead of downgrading.

Synthetic/native fixture success does not authenticate market prices or prove real
historical PIT, live trading or independent forward performance. The report retains
each source's declared data nature and evidence level. Real native multi-asset account
integration awaits those producers' authorized immutable outputs.
