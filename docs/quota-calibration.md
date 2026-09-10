# Quota calibration

Measured 2026-09-10 against `gpt-oss:20b-cloud` at `https://ollama.com/v1`, Ollama Cloud free tier.
Run directory: `runs/20260910T224550Z_f4f0da4d39e0`. Config hash `f4f0da4d39e0`.

## What one query costs

| Measure | Median | 95% CI | n |
|---|---|---|---|
| Seconds per query | 2.32 | 1.76 - 2.97 | 20 |
| Prompt tokens | 1,077 | 958 - 1,241 | 20 |
| Completion tokens | 176 | 121 - 250 | 20 |
| Reasoning share of output | 83% | 76% - 87% | 20 |

Failures during the run: 0 of 20.
Timing source: **client**.

## Does the endpoint report its own durations

**No.** The OpenAI-compatible surface returns `usage` token counts but no `eval_duration` or `prompt_eval_duration`, so **client wall-clock is the cost measure** and PLAN's open question is closed that way.

Wall-clock includes queueing behind the free tier's single concurrency slot, so it is an upper bound on GPU time. A budget built on it is conservative rather than wrong, which is the direction a budget should err in. It also means cost is only comparable between arms measured under similar load, which is why arms are run back to back rather than on different days.

### The native endpoint is a partial exception

PLAN 2a recommends the native `/api/chat` surface for eval runs because it reports `prompt_eval_duration` and `eval_duration`. Probed directly, `https://ollama.com/api/chat` returns `total_duration`, `prompt_eval_count` and `eval_count`, but does **not** return `prompt_eval_duration` and does **not** return `eval_duration` for this cloud model. Fields seen: `eval_count`, `prompt_eval_count`, `total_duration`.

| Probe call | Server `total_duration` | Client wall-clock |
|---|---|---|
| 1 | 1.26s | 1.48s |
| 2 | 1.25s | 1.47s |
| 3 | 1.84s | 2.05s |

`total_duration` is server-side and therefore a tighter measure than wall-clock, and the gap between the two columns is round-trip and queueing. It is still not the GPU-time breakdown PLAN wanted: without `prompt_eval_duration` there is no way to separate prompt processing from generation, so an arm that inflates the prompt and an arm that inflates the answer are indistinguishable on cost. The app keeps the OpenAI-compatible surface; an eval run that needs server time can call the native one and get a total, nothing finer.

## The budget

At 2.3s per query (1.8-3.0s), sequentially, one concurrency slot:

| Pass | Questions | Wall-clock |
|---|---|---|
| Dev slice | 60 | 2 min |
| Test split | 120 | 5 min |
| Full gold set | 300 | 12 min |

**Full gold-set passes per five-hour session window: 25.** That is throughput arithmetic, not an observed ceiling: nothing in this run tested what happens in hour four.

The metered ablation program is 10 arms on the 120-question test split: 1200 queries, 0.8 hours of sequential wall-clock.

**This is well under what PLAN budgeted for.** PLAN 2a sized the project around 5-15 seconds per query and a 12-40 minute pass; the measurement is 2.3s and 6 minutes for the same 150 questions. The consequence is that quota is not the binding constraint on Phase 4, and the OFAT restriction on the metered half is now a **statistical** decision rather than a budget one: 10 arms spend the test split 10 times, and a factorial design would spend it far more. Re-read that decision at Checkpoint D against the analysis plan, not against this page.

**83% of generated tokens are reasoning, not answer.** Output cost is dominated by a channel the user never sees, so any latency comparison between arms is mostly a comparison of how much the model thought. Answer length is close to noise inside it.

**No published cap was hit during this run**, and none is published to hit. The free tier meters GPU time with no stated RPM or TPM, so these figures are what the endpoint gave us on one day, not an entitlement. Treat a run that suddenly halves in throughput as throttling, not as a code regression.

## The context guard, recalibrated

`num_ctx` is set explicitly to 8192. The largest prompt in this run measured 1629 tokens.

Fitted from this run's `usage` counts: **3.80 characters per token** above a fixed chat-template overhead of **16 tokens**. The overhead is not a rounding detail: a seven-character prompt bills around seventy tokens on this model, so an estimator fitted without an intercept concludes a tenth of a character per token and refuses everything afterwards.

The shipped default stays at 3.2 characters per token, which is tighter than the fitted value and therefore still over-counts. Loosening a guard to the number that just fitted one day's prompts is how the guard stops guarding.

## Does an oversized prompt truncate silently

**Yes.** Sent ~15051 estimated tokens against num_ctx 8192; the server counted 8243 prompt tokens and answered without the fact planted at the front of the prompt. Nothing errored, nothing warned. This is the failure the guard in `OllamaCloudGenerator.check_prompt` refuses to let happen, and the reason it raises rather than trimming.

## How to reproduce

```
python scripts/calibrate_quota.py
```

Prompts are seeded, so a rerun measures the same twenty prompts against the same five passages each. The seconds will move with load; the prompt sizes will not.
