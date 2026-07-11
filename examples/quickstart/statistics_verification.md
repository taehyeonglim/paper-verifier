---
project: quickstart-demo
type: statistics-verification
---

# Statistics cross-verification (synthetic, N = 30)

Cross-validated analysis outputs for the quickstart demo. In a real project
this file is produced by your own analysis pipeline (e.g. an R lme4 model
cross-checked against a scipy reimplementation).

## 1. p-value verification (R vs scipy)

| DV | F | df1 | df2 | R p | scipy p | match |
|----|---|-----|-----|-----|---------|-------|
| Engagement | 5.212 | 1 | 28 | .030214 | .030216 | ✓ |
| Quiz Score | 4.873 | 1 | 28 | .035712 | .035714 | ✓ |

## 2. beta, SE, 95% CI verification

| DV | β | SE | 95% CI (Wald) | CI consistency |
|----|---|-----|--------------|----------------|
| Engagement | +0.512 | 0.224 | [0.073, 0.951] | ✓ |
| Quiz Score | +6.204 | 2.812 | [0.692, 11.716] | ✓ |

## 3. Wilcoxon + effect sizes

| DV | V | p | r (rank-biserial) | r 95% CI | dz (Cohen) | dz 95% CI | n |
|----|---|---|---|---|---|---|---|
| Engagement | 312.0 | .026431 | +0.412 | [0.156, 0.634] | 0.433 | [0.062, 0.801] | 30 |
| Quiz Score | 289.0 | .041228 | +0.377 | [0.101, 0.598] | 0.401 | [0.028, 0.770] | 30 |
