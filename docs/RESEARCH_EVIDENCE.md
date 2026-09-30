# Research evidence cards (11–16, 20)

```sh
quant-research-evidence family-evidence.json --sha256 <verified-input-sha256> --output family.html
quant-research-evidence paired-evidence.json --sha256 <verified-input-sha256> --output paired.html
```

The input hash is an independently supplied binding to the evidence snapshot. Rendering does
not rerun statistics or prove that source market data are genuine. Cards distinguish available,
failed, missing and not-requested methods; full candidate/attempt and sensitivity evidence is
retained in the HTML. All input text is escaped.

DSR is selection-adjusted evidence, not a probability of profit. CSCV is not chronological OOS.
SPA/MCS conclusions apply to the declared whole family. Show every bootstrap block length.
Controlled return-gap effects are not causal; residuals are not identified interactions.
Passive, same-risk-constrained and zero-interest cash are different benchmark definitions.

`render_study(source, output, registry_path=...)` supports an explicit shared trial database,
verifies existing registration/result/artifact integrity, shows ex-ante objective statuses and
labels continuous versus independent-fold accounts correctly. Missing objective evidence is
not an acceptance pass. Existing studies and default independent-fold semantics are unchanged.
