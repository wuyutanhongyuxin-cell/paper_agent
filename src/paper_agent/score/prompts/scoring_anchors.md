# Scoring Anchors (Anti-Inflation)

> paper-agent 0.1.1 — `score/dimensions.py` 7-dim scoring system.
> Sourced from PaperOrchestra (MIT) `skills/paper-autoraters/references/scoring-anchors.md`,
> adapted for paper-agent. Paper-agnostic: contains no discipline / language
> hardcoded terminology.

## Why Anchors

Without explicit interval anchors, LLM judges drift toward the 75–85 band by
default (well-documented inflation bias; Sakana AI-Scientist v2 and PaperOrchestra
both adopt anchored prompts as the standard mitigation). Anchors force the LLM
to first commit to an interval, then pick a number within it.

## The 7 Intervals (0–100 integer)

| Interval | Label | Meaning |
|----------|-------|---------|
| 0–20     | fatally flawed       | Unintelligible or fundamentally invalid. Cannot be revised; must be discarded or redone from scratch. |
| 21–40    | substantially flawed | Major structural problems. Salvageable only via near-complete rewrite. |
| 41–55    | significant issues   | Mostly descriptive without critical synthesis; substantive gaps. Heavy revision required. |
| 56–70    | acceptable           | Competent but unremarkable. Reads as solid undergraduate / early-graduate work. Minor revisions sufficient. |
| 71–85    | strong               | Publishable as-is in a reputable venue. Clear contribution, sound execution, identifiable but minor weaknesses. |
| 86–92    | excellent            | Exceptional work, extremely rare. Field-relevant impact likely. Use sparingly. |
| 93–100   | exceptional          | Field-defining, paradigm-shifting. Reserve for once-per-decade work. |

## LLM Prompting Contract

The evaluator prompt MUST:

1. Show the table above verbatim.
2. Instruct the LLM to **first state the interval** (e.g., "I select 41–55")
   and explain the choice in one sentence before naming the integer score.
3. For any score in `71–85` or above, require the LLM to cite at least one
   concrete `{file, line}` evidence reference.
4. For `86–92` and `93–100`, require the LLM to explicitly justify why the
   work is "extremely rare" / "field-defining" — without such justification,
   automatically downgrade to `71–85`.

This contract is enforced by `paper-agent verify-score` (0.1.1 / 0.2.0):
evidence `{file, line}` references are reverse-checked via `grep -n`. If the
cited line does not contain reasoning support, the dimension score is
invalidated and the run is excluded from ensemble aggregation.

## The 7 Dimensions

Names and order are frozen (contract); meanings are intentionally generic so the
schema applies across disciplines and languages.

| Dimension       | Generic meaning |
|-----------------|-----------------|
| rigor           | Methodological soundness; statistical / experimental / proof discipline. |
| novelty         | Differentiation from prior work; originality of contribution. |
| clarity         | Readability; structural coherence; precision of prose. |
| reproducibility | Openness of code / data / hyperparameters / artifacts. |
| related         | Coverage, relevance, and critical synthesis of prior literature. |
| significance    | Anticipated impact within and beyond the immediate subfield. |
| ethics          | Data provenance; participant consent / IRB; safety; dual-use considerations. |

Sub-dimension decomposition (e.g., `related` → coverage / relevance / critical
synthesis per PaperOrchestra `litreview-quality-prompt.md`) is delegated to the
M-E ensemble layer; the M-D dimensions schema treats each top-level field as a
single integer + reasoning block.

## Confidence Tiers (Self-Reliability α)

After ensemble aggregation (M-E), the Krippendorff α over the `run_scores` array
of any single dimension is interpreted via the following tiers:

| α range       | confidence label | downstream behavior |
|---------------|------------------|---------------------|
| α ≥ 0.80      | `high`           | Substantial agreement; ensemble score is the final score. |
| 0.67 ≤ α<0.80 | `low`            | Low-confidence pass; downstream consumers MUST surface the label. |
| α < 0.67      | `fail`           | Result invalidated; re-run ensemble. After 3 failures, escalate. |

Default thresholds (`alpha_min_threshold=0.67`, `alpha_target_threshold=0.80`)
follow Rating Roulette (Haldar & Hockenmaier, EMNLP 2025 Findings,
arXiv:2510.27106) for LLM-judge self-reliability.

## Compatibility

This file is read by:
- M-E `score/ensemble.py` — prompt construction.
- M-E `score/red_team.py` — anchor reference in stress prompts.
- Any external `evaluator: Callable` injected into the M-D schema.

It is **never** read or written by the Edit Gate (L-033 contract: anchors
inform LLM judges, not paper.tex). M-D modules dump structured scores only;
they do not mutate the paper source.
