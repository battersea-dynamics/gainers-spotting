# Gainers Spotting engine specification v2

**Status:** Approved for phased research implementation  
**Specification version:** `engine-spec-v2`  
**Approved:** 2026-09-15  
**Repository:** `battersea-dynamics/gainers-spotting`

## 1. Purpose

This specification refines the engine after the first whole-market five-minute pilot.
The objective is to discover US-traded stocks whose point-in-time after-hours,
premarket, and early-opening behaviour resembles patterns that have previously
led to a substantial remaining intraday rise.

The engine must not start from a fixed ticker list or from Revolut membership.
It must construct a fresh eligible-stock universe and discover candidates from
market data available at the decision time.

The primary causal hypothesis for v2 is:

`unusual current activity -> strengthening price/volume structure -> possible remaining spike`

Historical dormancy is not required. A stock can qualify whether it was quiet,
active, or volatile in earlier sessions.

## 2. Binding boundaries

1. Work only in `battersea-dynamics/gainers-spotting`.
2. Do not modify or couple to `battersea-dynamics/trading-agent`.
3. Do not access positions, account balances, orders, or order endpoints.
4. Do not submit live or paper orders.
5. Produce research rankings at 09:30, 09:45, and 10:00 ET.
6. The 09:30 ranking may use only information available before 09:30 ET.
7. The later rankings may add completed regular-session information available
   by their respective timestamps.
8. Keep point-in-time rankings separate from later outcomes.
9. Keep Revolut observations outside universe construction and ranking inputs.
10. Do not impose a discovery price floor merely because a stock is cheap.
11. Do not treat a discovered candidate as automatically suitable to trade.

## 3. Approved v2 design decisions

### 3.1 Stock-only primary universe

The primary ranking universe contains exchange-listed:

- common shares;
- ordinary shares;
- ADRs or ADSs representing operating companies.

The primary ranking excludes:

- ETFs, ETNs, mutual funds, closed-end funds, and other pooled products;
- warrants and rights;
- preferred shares;
- bonds and other debt securities;
- SPAC units;
- any instrument whose available metadata confirms that it is not stock.

SPAC common shares remain stocks but must carry a separate `SPAC_COMMON` flag.
Unknown instrument types must be placed in an unclassified control output and
must not enter the primary stock ranking until their type is resolved. Security
type must not be guessed from price behaviour.

Alpaca's `us_equity` asset class is not sufficient security-type evidence by
itself because it can include stocks and non-stock exchange-listed products.
The classifier therefore requires a separately versioned daily security master.
The initial implementation should test the official Nasdaq Trader symbol
directory fields, combined with Alpaca metadata and SEC issuer identity. If
those sources cannot resolve a security safely, the result remains unknown
rather than being inferred from the issuer name alone.

There is no fixed symbol list. Eligibility is reconstructed and versioned for
each session.

### 3.2 Dormancy is descriptive, not a gate or ranking channel

The pilot's `dormant_activation` candidate channel is removed from primary
candidate selection. Historical activity and volatility may remain as context
for later analysis, but they shall not:

- be required for eligibility;
- exclude an active candidate;
- add ranking points merely because a stock was previously quiet.

This permits an actively traded biotechnology company, for example, to qualify
when a new trial result produces compelling current premarket behaviour.

### 3.3 Activation first, catalyst second, risk third

The engine uses three separately observable profiles:

1. **Market activation:** what price, volume, trades, and structure are doing
   now.
2. **Catalyst confidence:** whether timely external evidence plausibly explains
   the move.
3. **Execution risk:** whether the observed opportunity may be difficult or
   hazardous to implement.

The profiles must remain separate in stored data. The pilot's equal average of
unrelated channel scores is not the v2 final ranking method.

## 4. Processing funnel

### Stage A — Dated dynamic universe

Capture all active and supported US exchange-listed instruments, classify the
instrument type, and preserve the complete snapshot and its content hash.

Outputs:

- primary stock universe;
- excluded non-stock instruments with reason codes;
- unresolved-instrument control set;
- counts and coverage by instrument type and exchange.

### Stage B — Broad market activation pass

Use batched five-minute bars across the primary stock universe. Calculate only
features that can be produced consistently and economically at market scale.

The broad pass should retain candidates through independent activation routes:

- **established activity:** already meaningful dollar volume and trade flow;
- **abnormal activity:** current activity is exceptional relative to the same
  stock at the same premarket time on previous sessions;
- **emerging acceleration:** recent price and volume velocity are increasing;
- **constructive structure:** strength is persistent rather than one isolated,
  stale print.

The union is a recall-oriented research set, not the final ranked shortlist.

### Stage C — One-minute candidate analysis

For the broad candidate union, collect one-minute bars and, where available,
quotes. Recalculate detailed activation and structure features using strict
completed-bar rules.

### Stage D — Selective catalyst enrichment

Only after quantitative reduction, query timestamped news, regulatory filings,
corporate actions, and other context for the retained candidates. Missing news
must not imply that no catalyst exists.

### Stage E — Optional specialist enrichment

For the smaller enriched set, add options, float, short-interest, analyst, and
sector context when the source is available and point-in-time valid. A stock
without options must not be penalised merely for being non-optionable.

### Stage F — Evidence rankings

Produce separate evidence profiles and decision-time rankings. The final model
must be chosen by chronological held-out testing, not by the best result on the
pilot session.

## 5. Market-activation features

### 5.1 Previous-close and after-hours context

- previous official regular-session close;
- verified gap from that close to the latest eligible price;
- previous-session after-hours first, last, high, low, volume, dollar volume,
  and trades;
- whether movement began in after-hours or the current premarket;
- after-hours persistence or fade;
- premarket reacceleration;
- latest price relative to the after-hours close and high.

Gap fields must remain unavailable when corporate-action adjustment cannot be
verified safely.

### 5.2 Current activity

- cumulative premarket share and dollar volume;
- cumulative trade count and active bars;
- volume and dollar volume in the latest 5, 15, and 30 minutes;
- time-of-day share and dollar relative volume;
- log activity surprise relative to the stock's own same-cutoff history;
- volume velocity and acceleration;
- late-premarket share of total activity;
- time of first meaningful activity;
- staleness of the last eligible observation.

Today's 04:00–07:00 ET activity must be compared with historical activity only
through 07:00 ET, not with historical full-premarket totals.

### 5.3 Price path and structure

- verified previous-close-to-current return;
- 5-, 15-, and 30-minute returns;
- price velocity and acceleration;
- premarket range position;
- distance and time from the premarket high;
- VWAP distance and VWAP retention;
- higher-high and higher-low evidence;
- new-high count and frequency;
- maximum pullback and recovery;
- early spike followed by fade;
- consolidation near the high;
- volatility expansion;
- movement already completed versus estimated remaining opportunity.

Every window retains bar coverage and no-trade state. Missing candles must not
be fabricated as zero-volume candles.

### 5.4 Opening confirmation

At 09:45 and 10:00 ET only, add:

- open-to-decision return;
- opening dollar volume and relative activity;
- opening-range position;
- opening VWAP position;
- price relative to the known premarket high;
- opening pullback and recovery;
- new-high or failure evidence;
- change in activation rank since the previous decision.

## 6. Catalyst-confidence layer

### 6.1 Catalyst sources

The initial source order is:

1. Timestamped Alpaca/Benzinga news available under the configured entitlement.
2. SEC EDGAR submissions and filing documents.
3. Alpaca corporate-action announcements.
4. A separately approved earnings or event-calendar provider if required.
5. Company press releases only through a reliable licensed feed or verified
   issuer source; do not build a fragile market-wide website scraper.

Useful event families include:

- clinical-trial, FDA, or other regulatory results;
- earnings, guidance, or material business updates;
- contracts, partnerships, licences, or customer wins;
- mergers, acquisitions, tender offers, or strategic investment;
- analyst upgrades, downgrades, and target changes;
- insider purchases or sales reported on Form 4;
- new greater-than-5% beneficial ownership reported on Schedule 13D or 13G;
- financing, shelf registration, ATM programme, offering, or convertible debt;
- stock split, reverse split, merger, spinoff, or other corporate action;
- litigation, exchange-compliance, delisting, or trading-halt information.

### 6.2 Required catalyst record

Each item must preserve:

- `symbol`;
- `source` and stable source identifier;
- source URL when available;
- headline or filing form;
- event category;
- positive, negative, mixed, or unknown direction;
- source publication timestamp;
- first information-available timestamp;
- engine retrieval timestamp;
- age at the decision;
- deterministic or model classification version;
- confidence and ambiguity flags.

A revised article or filing must not be backdated to its earlier version in a
historical replay.

### 6.3 Catalyst use during research

The first implementation stores catalyst tags without changing the quantitative
activation rank. It then measures, on later dates, whether a catalyst category
improves remaining-MFE, forward return, MAE, or fade probability within a
comparable activation cohort.

Only catalyst effects that persist in chronological held-out tests may earn a
bounded ranking adjustment. A catalyst must not rescue a stock with no current
market activation.

An optional LLM may classify a small final set into a strict JSON schema. It may
not calculate market features, invent missing facts, or replace the underlying
headline, filing, timestamp, and deterministic audit record.

## 7. Options and large-investor evidence

### 7.1 What can be measured

Where data are available, candidate-level options context may include:

- optionable status;
- prior-session and current eligible-session call and put volume;
- call/put volume imbalance;
- volume relative to open interest;
- concentration by expiry and strike;
- near-term out-of-the-money call activity;
- implied volatility level and change;
- bid/ask quality and data coverage;
- unusually large prints relative to that contract's normal activity.

### 7.2 What must not be claimed

Public option prints normally do not identify the institution or prove whether
a call was bought, sold, hedged, or one leg of a larger strategy. The engine
must therefore use reason codes such as `UNUSUAL_CALL_ACTIVITY`, not claims such
as `BIG_FIRM_EXPECTS_RISE`.

Premarket single-stock options coverage is limited and changing. Every options
feature must state its eligible session, venue coverage, timestamp, and whether
it represents live volume, a previous-session observation, or prior open
interest.

Options evidence is supporting context. It cannot be a universal requirement
because many small stocks are not optionable.

### 7.3 Institutional disclosures

- Form 13F holdings are quarterly and can be filed up to 45 days after quarter
  end. They are background context, not a next-morning trigger.
- Schedule 13D/13G filings may identify a greater-than-5% owner and can be an
  event tag when available before the decision.
- Form 4 may identify insider transactions but can arrive after the transaction.

Every filing signal uses the public filing timestamp, never the earlier
transaction date, as its information-available time.

## 8. Additional contextual features

### 8.1 Float and share structure

Where a historically valid source is available, retain:

- public float and shares outstanding;
- source date and age;
- market capitalisation;
- premarket volume as a fraction of float;
- recent issuance or dilution change.

Stale or inconsistent float data must be flagged. Float rotation must not be
used when the denominator is not point-in-time reliable.

### 8.2 Short interest and borrow context

Potential fields include reported short interest, percentage of float, days to
cover, report date, publication date, and—only if a suitable provider exists—
borrow availability or cost.

Official short interest is delayed and is not a live statement of current short
positions. It may describe squeeze susceptibility but must not be treated as a
same-day catalyst.

### 8.3 Sector and broad-market context

Retain sector/industry performance, broad-index direction, volatility regime,
and whether related stocks are moving simultaneously. This helps distinguish a
company-specific catalyst from a sector-wide move.

## 9. Ranking design

### 9.1 Hard eligibility and data gates

A primary ranking row requires:

- confirmed eligible stock type;
- at least one current-session premarket trade before the cutoff;
- a non-stale price under the configured research protocol;
- sufficient valid observations for its selected activation route;
- no fatal run-level data-quality failure.

Exact staleness and observation thresholds remain research parameters and must
not be selected from the single pilot session.

### 9.2 Separate scores

Initially expose rather than obscure:

- `activation_score`;
- `momentum_quality_score`;
- `catalyst_confidence`;
- `execution_risk_profile`;
- component coverage and reason codes.

Do not calculate a consensus by averaging every available channel. Candidate
routes with different purposes must not dilute the strongest activation route.

### 9.3 Candidate ordering to test

Chronological research shall compare at least:

1. abnormal-activity rank alone;
2. activation plus momentum-quality rank;
3. activation plus a bounded confirmed-catalyst adjustment;
4. the same models with execution-risk stratification;
5. simple baselines: verified gap, dollar volume, relative volume, and distance
   from premarket high.

No final weights, probability cutoffs, or `BUY` classification are approved in
this specification.

### 9.4 Human-facing output

At each decision, show a concise ranked research list containing:

- symbol and company;
- current price and verified gap;
- activation and momentum ranks;
- strongest market reason codes;
- catalyst category, age, and confidence;
- options or ownership context when available;
- liquidity, spread, dilution, staleness, and data-quality warnings;
- change from the previous checkpoint;
- `research_only: true` and `orders_supported: false`.

## 10. Point-in-time safeguards

Every input record must retain both event time and information-available time.
An input is eligible only when its information-available time is no later than
the decision timestamp.

Required protections include:

- completed-bar plus configured-feed-delay enforcement;
- no 09:30 use of regular-session bars;
- no use of a filing, headline, analyst action, or event revision published
  after the decision;
- no use of end-of-day float, volume, high, or sector outcome in an earlier
  ranking;
- no use of future open-interest changes;
- no winner-derived universe or fixed candidate list;
- immutable point-in-time ranking artifacts generated before outcomes are
  joined.

## 11. Evaluation plan

### 11.1 Required comparisons

For every decision and model, report:

- precision at top 5, 10, and 20;
- recall and total candidate burden;
- remaining MFE and MAE;
- returns after 5, 15, 30, 60, and 120 minutes and to close;
- time to MFE and first material adverse move;
- probability of a new high after the decision;
- high-to-close giveback and opening-fade frequency;
- results with and without catalyst, options, float, and risk features;
- misses and false positives by reason.

### 11.2 Ablation requirement

New data justify their cost only if held-out tests show incremental value.
Evaluate in this order:

1. price/volume activation baseline;
2. plus one-minute structure;
3. plus catalyst tags;
4. plus options/institutional context;
5. plus execution-risk treatment.

This prevents a large collection of attractive-sounding fields from hiding
which information actually helps.

### 11.3 Chronological validation

Use expanding-window walk-forward testing:

1. define or fit the rule on earlier dates;
2. freeze the version;
3. evaluate it on the next unseen date or date block;
4. record the result before any revision.

The single 2026-09-11 whole-market pilot is pipeline evidence only. Final model
selection requires a substantially larger multi-regime sample and subsequent
no-order observation sessions.

## 12. API- and cost-aware collection

The intended request funnel is:

1. entire stock universe: metadata, daily reference data, and batched
   five-minute bars;
2. broad activation union: one-minute bars and available quotes;
3. reduced candidates: news, SEC, corporate actions, and company context;
4. small finalist set: options and any optional structured LLM classification.

Every run reports calls, pages, retries, failures, cache hits, cache misses,
bytes, runtime, entitlement gaps, and candidate counts at each stage.

Historical data, filings, and classified catalysts should be cached using
source, symbol, time window, publication timestamp, and schema/model version.
Credentials remain in environment variables or secure GitHub secrets and must
never be logged or committed.

## 13. Implementation sequence after approval

### Phase 1 — Correct the quantitative pilot

- classify instruments and make the primary ranking stock-only;
- preserve excluded and unresolved instruments as control outputs;
- remove `dormant_activation` from candidate selection;
- replace the equal channel-average consensus with separate activation and
  momentum-quality rankings;
- require current premarket activity for a primary candidate;
- add regression tests reproducing the original pilot comparison.

### Phase 2 — Improve the activation evidence

- collect candidate one-minute bars;
- build historical same-time-of-day premarket baselines;
- add robust 5-, 15-, and 30-minute acceleration and structure features;
- add quote/spread inputs where entitlement permits;
- validate corporate-action-adjusted gap calculations.

### Phase 3 — Add selective catalysts

- integrate timestamped news and SEC filing metadata;
- add corporate-action and dilution classification;
- store deterministic catalyst records without changing the rank initially;
- measure catalyst value on later sessions.

### Phase 4 — Add optional specialist context

- test options features on optionable candidates;
- evaluate point-in-time float and short-interest sources;
- add sector and market-regime context;
- retain only features that improve held-out results or useful risk reporting.

### Phase 5 — Validate and observe

- repeat independent whole-market collection across multiple regimes;
- freeze candidate budgets and model versions chronologically;
- run no-order live observation for at least 20–30 sessions;
- consider paper-trading research only after a separate evidence review and
  explicit approval.

## 14. Source capability references

- Alpaca historical stocks, options, and news:
  <https://docs.alpaca.markets/us/docs/historical-api>
- Alpaca historical news:
  <https://docs.alpaca.markets/us/docs/historical-news-data>
- Alpaca option-chain snapshots:
  <https://docs.alpaca.markets/us/reference/optionchain>
- Alpaca corporate actions:
  <https://docs.alpaca.markets/us/reference/corporateactions-1>
- SEC EDGAR APIs:
  <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>
- SEC insider transactions and Form 4 timing:
  <https://www.sec.gov/files/forms-3-4-5.pdf>
- SEC Form 13F timing:
  <https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f>
- SEC beneficial-ownership reporting:
  <https://www.sec.gov/newsroom/press-releases/2023-219>
- FINRA equity short interest:
  <https://www.finra.org/finra-data/browse-catalog/equity-short-interest>
- Nasdaq Trader symbol-directory field definitions:
  <https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs>

## 15. Approved choices

The following choices were approved on 2026-09-15:

1. ADRs/ADSs representing operating companies remain in the primary stock
   universe, with an instrument-type label.
2. SPAC common shares remain eligible stocks but are separately flagged.
3. Unknown security types remain outside the primary rank until resolved.
4. Catalyst tags are measured first and cannot change ranking weights until
   later-date evidence supports them.
5. Options and institutional evidence remain supporting context, not a claim
   that a named large firm expects the stock to rise.
