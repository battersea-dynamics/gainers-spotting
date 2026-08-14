# Evidence-Based Improvements for Gainers Spotting

**Purpose**  
Reference document for the testing and refinement phase. These recommendations address the main gaps identified in the current research architecture (small sample, open outcome definitions, limited fill realism, feature robustness, and practical utility measurement). Every item is grounded in the project’s existing methodology principles (no look-ahead, no invented thresholds, discovery ≠ tradability, post-open data only for evaluation) and in established equity microstructure and quant research practice.

## 1. Expand and Stratify the Historical Sample (Highest Priority)

**Current gap**  
Only one original day (2026-07-24) plus one observed week (27–31 July). Premarket continuation behaviour is known to be strongly regime-dependent.

**Evidence-based actions**
- Collect and analyse at least 40–60 additional trading days spanning distinct regimes: high-VIX vs low-VIX, earnings-heavy weeks vs quiet weeks, strong vs weak market breadth, and different days of the week.
- Stratify all analyses by regime (e.g. VIX quintiles, overnight futures move, number of earnings releases). Report results both pooled and within-regime.
- Maintain the existing leave-one-date-out protocol; never mix discovery and validation dates.
- Explicitly track and report how many “significant gainers” appear in each regime so that positive-class prevalence is visible.

**Rationale**  
Large-gap statistics consistently show that continuation rates, fade rates, and MFE/MAE distributions change materially with volatility and catalyst density. A summer-only sample will under- or over-state edge.

## 2. Freeze Multiple Outcome Definitions Before Feature Selection

**Current gap**  
“Significant gainer” and “useful remaining move” are still open questions. Any ranking that optimises a single post-hoc label will overfit.

**Evidence-based actions**
- Define and freeze a small family of continuous and binary labels *before* ranking features:
  - Maximum favourable excursion (MFE) after each decision time (09:30 / 09:45 / 10:00).
  - Time-to-MFE and time-to-first-adverse-excursion of X%.
  - Return from decision price to subsequent high, to noon, and to close.
  - Binary labels at several fixed remaining-move thresholds (e.g. +15 %, +25 %, +40 % from decision price) treated only as evaluation labels, never as training targets until frozen.
  - Explicit failure modes: “faded within 30 min”, “never made new high after decision”, “high-to-close giveback > 50 % of MFE”.
- Report every candidate ranking against *all* of these labels simultaneously. Prefer rankings that improve multiple labels rather than one spectacular metric.
- Never use future information (including the final day’s high) when constructing features or selecting cut-offs.

**Rationale**  
Public gap studies show that large premarket gaps frequently produce high MFE but also high fade rates in the first 60 minutes. A single binary “top gainer” label hides this trade-off.

## 3. Improve Fill Realism and Liquidity Modelling

**Current gap**  
Last premarket price and the official opening print are treated as research benchmarks, not claimed fills. Realistic slippage and auction dynamics are still missing.

**Evidence-based actions**
- For every hypothetical entry, record both the decision-time last trade *and* a conservative fill proxy:
  - Opening auction: use the first regular-session bar open only as an upper-bound optimistic fill; also compute a more conservative fill (e.g. volume-weighted price of the first 1–3 minutes or a fixed adverse ticks assumption).
  - Premarket entry: never assume the last print is executable; apply a liquidity-dependent haircut based on premarket dollar volume and trade count in the final 15–30 minutes.
- Add simple liquidity filters as *evaluation* layers (not discovery filters): minimum premarket dollar volume, minimum trade count, maximum estimated spread proxy (high–low of final premarket bars or first regular bars).
- Explicitly measure the distribution of “decision price vs achievable open price” across the sample. Report how often the optimistic open fill is materially better or worse than a conservative fill.

**Rationale**  
Equity auction research and practitioner data both show that premarket last prices on thin volume frequently diverge from the opening cross once real institutional size appears. Treating the open print as automatically achievable systematically overstates edge.

## 4. Systematic Feature Freezing and Robustness Testing

**Current gap**  
Many promising features (acceleration, time-normalised RVOL, persistence, dormant-to-active transitions, distance from premarket high, VWAP behaviour) are still hypotheses.

**Evidence-based actions**
- Freeze a modest feature set (price/gap, path/timing, activity/liquidity, structure) on an early subset of dates *before* inspecting outcomes on later dates.
- Test every feature for robustness to extremes: low-priced names, very low volume names, and stocks with incomplete premarket bars. Document failure modes rather than discarding the names.
- Always report rank correlations and effect sizes against the simple baselines already planned (gap rank, dollar-volume rank, raw RVOL rank). Any more complex ranking must demonstrably improve on these baselines on held-out dates.
- Prefer features that are computable with only completed bars available at the decision timestamp (strict causality).

**Rationale**  
Acceleration and relative volume are repeatedly cited in gap-continuation studies as the variables that most improve continuation probability, but they are also the most sensitive to denominator problems and thin-tape artefacts.

## 5. Explicit Alert-Burden and Practical Utility Metrics

**Current gap**  
Precision/recall are necessary but incomplete for a scanner that a human (or later system) must actually act on.

**Evidence-based actions**
- For every candidate ranking and every decision time, report:
  - Average and distribution of candidate-set size.
  - Precision at fixed k (top 5, top 10, top 20).
  - Number of true positives that would have been missed if the set were limited to a realistic daily alert budget.
  - False-positive reasons (faded, insufficient remaining move, liquidity failure).
- Track “detection lead time vs remaining move” scatter plots so the confirmation-vs-upside trade-off is visible.

**Rationale**  
A ranking that recovers 80 % of eventual big movers but surfaces 40 names every morning is practically useless. Alert burden is a first-class research metric.

## 6. Catalyst and Qualitative Layer (After Quantitative Reduction Only)

**Current gap**  
Catalyst enrichment is correctly deferred, but the interface is still undefined.

**Evidence-based actions**
- After quantitative candidate reduction, apply a lightweight structured tag (earnings, FDA, analyst action, M&A rumour, pure momentum, unknown) using only information available before the decision timestamp.
- Measure whether catalyst type materially changes continuation rates *within* the same quantitative cohort. Do not let the catalyst override the quantitative rank until that evidence exists.
- Keep any LLM use strictly post-reduction and limited to the final short list.

**Rationale**  
Catalyst type is one of the strongest known modulators of gap continuation versus fade, but only after the quantitative filter has already reduced the universe.

## 7. Forward-Testing Protocol Once Rules Are Frozen

**Current gap**  
The project correctly stays in pure historical research for now.

**Evidence-based actions**
- Once a ranking rule is frozen on the expanded historical sample, move to observation-mode live scanning (no orders) for a minimum of 20–30 additional sessions.
- Log every alert with the exact information set available at decision time, the eventual outcomes against the frozen labels, and any liquidity or fill surprises.
- Only after that evidence is reviewed should paper-trading research be considered.

**Rationale**  
Historical leave-one-date-out is necessary but still in-sample relative to the market regime of the collection period. Live observation is the next causal step.

---

**Implementation note**  
None of the above requires inventing production thresholds or changing the project’s core principles. All items can be implemented as additional analysis layers or expanded data-collection scripts while preserving the existing bias controls and research-only boundary.

This list should be treated as living guidance: update it with findings as the multi-date and regime-stratified results become available.
