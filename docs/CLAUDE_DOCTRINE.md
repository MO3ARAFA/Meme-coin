# How Claude is (and is not) used in this project

Read before opening a session. This is an operating constraint, not documentation.

## Why
Claude makes iteration cheap. Cheap iteration raises the number of things tried, and the number of things
tried is the denominator of every significance test here (Deflated Sharpe). Used in the wrong place Claude
makes the research *worse*, not faster. Claude also tends to agree with whoever is talking to it: given a
hopeful framing it writes a hopeful analysis; given a rejected result it finds "promising signs".
Claude is not a source of edge, a judge, or a generator of hypotheses.

## What Claude does
| Role | Allowed | Example |
|---|---|---|
| Implementation | write code, tests, refactors, docs, CLIs, known statistical formulas | "Write a test that bootstrap returns None for n < 3" |
| Refutation | build the strongest argument AGAINST a hypothesis, from the hypothesis text and data only | "State the best statistical case that H2 is noise" |
| Description | say what the numbers are: counts, medians, concentration, bias sources | "Describe the trade distribution and which trades drive PnL" |
| Code review | find bugs in calculations | "Review the profit-factor code for errors" |

## What Claude does not do
* Propose trading hypotheses, parameters or thresholds ("suggest 5 new strategies").
* Judge results or predict the market ("what do you think?", "will this work live?", "is this promising?").
  A question containing *what do you think* or *do you believe* is out of scope by definition.
* Write prompts meant to make Claude find an edge.
* Edit, reset or hide the trial ledger.

## Mechanics
1. **Hypotheses are human.** Each is written in `docs/PREREGISTRATION_*.md` before data is touched.
2. **The ledger is code, not conversation.** `data/trials*.json` is changed only by `research_log.record_trial`
   as a side effect of running an evaluation. Nobody edits it by hand. Claude can *read* it (it cannot be
   hidden in a session that shares the repo), so the control is accountability: each entry records its
   source (`human` or `claude-suggested`), and anything Claude suggested in passing is counted like any other try.
3. **Separate contexts for separate jobs.** For refutation or description give Claude the hypothesis text and
   the data, not your hopes, not earlier attempts, not "I think this will work". Context you add is
   tone you get back.
4. **Ask for a refutation, not a review.** "Find flaws" produces ritual criticism ending in "but worth trying".
   "Construct the strongest case that this result is chance" does not.
5. **Verdicts come from gates and from paper trading.** Never from a paragraph written by Claude.

## Known failure (watch for it)
A casual late-night question, "what do you think?", gets a wise-sounding answer; you adjust a threshold;
that is an uncounted trial; the gates reject two weeks later; repeat. Nothing in the system stops this except
this page. A breach is allowed to happen. It is not allowed to stay invisible: write it in the ledger.

## Honest limits of this doctrine
* It cannot technically prevent anyone from asking. It makes breaches visible and countable.
* Earlier in this project Claude proposed things (for example lowering the liquidity floor to widen the
  sample). None were run, and the pre-registration forbids running them without counting.
