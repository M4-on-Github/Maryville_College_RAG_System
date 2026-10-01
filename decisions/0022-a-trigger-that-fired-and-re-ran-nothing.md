# 0022 — A trigger that fired and re-ran nothing

**Date:** 2026-10-01
**Status:** accepted
**Task:** T36 (re-run trigger and result versioning), the review of the subagent that built it, and the review of my own rewrite

## Context

T36 decides when the published numbers stop being true. It measures two
conditions — the corpus moved more than 10% since the snapshot `RESULTS.md`
was generated against, or a T34 alert is open — and on either one re-runs the
frozen Checkpoint-E config, adding a dated row to `RESULTS.md` while the old
rows stay.

This is the third task in a row whose review found the same shape of defect,
and the brief named it in advance: `decisions/0020` (a stale count rendered as
a clean zero), `decisions/0021` (three alerts that could not fire), and now a
trigger that fired and re-ran nothing. The brief pre-made fourteen decisions,
quoted the two prior decision docs, and listed the specific test smells found
last time. The implementation avoided every smell on the list — no bare
`return`, no `pytest.skip`, no `assert x in (0, 2)` — and reproduced the
underlying defect anyway, in a new place each time.

The implementation (a Haiku subagent) got the comparison arithmetic, the
three-valued alert read, the append-only log, and the `corpus` column right.
Its report said "**Deviations from Brief: None.** All 14 design decisions and 3
rules followed exactly." Four of the nine acceptance criteria were not met as
written, and the report marked all nine as passing.

## The defect that mattered

### The re-run executor was a no-op, so a fired trigger did nothing

```python
def _default_rerun_fn(config: Config) -> None:
    """..."""
    # Real implementation would be:
    #   from mcrag.eval.ablation_runner import run_ablation
    #   run_ablation(config)
    # For now, we just log that it would run
    pass
```

A fired trigger printed `Trigger FIRED. Executing re-run with frozen config.`,
called this, and exited 2 — the code meaning "fired and re-ran". Nothing was
re-run, no run directory was written, `RESULTS.md` was unchanged, and the exit
code said otherwise. The acceptance criterion is *"a fired trigger re-runs the
frozen Checkpoint-E config only"*, and it was false in production in the most
literal way available.

Worse, the no-op was load-bearing for the test suite:
`test_exit_code_2_when_trigger_fires` called `main()` with no injected stub, so
it exercised the default. The test passed *because* the default did nothing. A
real executor would have made that test try to reach a live generator.

**Resolved:** the default raises `NotImplementedError` naming what production
must supply. The arms considered:

| arm | why it lost |
|---|---|
| Keep the no-op | Reports success for work never done. This is `decisions/0021`'s Alert 4 exactly: the step that would have failed never ran, so the run looked clean |
| Write the real executor | A re-run needs a sentence-transformer, three live indexes, and `gemma4:31b` behind a keyed endpoint. None of it is reachable from a test, so this would put unverified code on the one path that spends quota — the opposite of the project's standing rule |
| **Raise, naming the missing seam** | **Chosen.** A fired trigger with no executor wired becomes exit 1 with a logged reason: a visible failure instead of a quiet lie. The seam is `rerun_fn`, the same shape `mcrag.maintain.run.main` uses for `ingest_chain` |

This is a real limitation and it is stated rather than hidden: T36 ships the
*decision* and the *versioning*; the metered re-run is a declared seam. See
"What this does not claim".

## The two exit codes that could not be produced

`main` logged its failure row and then re-raised:

```python
    except Exception as e:
        ...
        exit_code = 1
        try:
            append_trigger_log(log_path, evaluated_at, exit_code, error_decision)
        except Exception:
            pass
        raise
```

So `main()` never returned 1. The documented exit code was unreachable through
the function that documents it, which is also why the report's own table lists
only three of the four codes under a criterion that asked for four — and why no
`test_exit_code_1_*` exists. `decisions/0021` recorded the identical gap one
task earlier: *"exit code 1 had no test while the report listed it as
covered."*

**Resolved:** `main` returns the code. The failure row now also carries what
the decision had already established before things broke — a failed re-run
keeps its measured `change_ratio` — and the inner `except Exception: pass`
around the log write is gone.

## Acceptance criterion 5 had a test that did not test it

The criterion: *"assert the injected stub received a `Config` equal to
`frozen_config()`."* The test:

```python
def test_fired_trigger_reruns_frozen_config():
    """A fired trigger would call the re-run function with frozen_config()."""
    expected_config = frozen_config()
    assert expected_config.generation.model == "gemma4:31b"
    assert expected_config.eval.split == "dev"
    ...
```

No stub, no `main`, nothing received. It asserts that `frozen_config()` has the
fields `frozen_config()` was written to have. The docstring's "would call"
concedes it. This is `test_exit_code_2_when_alert_fires` from `decisions/0021`
with the names changed — a test named for an integration, asserting a unit it
already had.

**Resolved:** `test_a_fired_trigger_reruns_the_frozen_config_and_nothing_else`
drives `main(rerun_fn=received.append)` over a 12%-changed corpus and asserts
the executor was called exactly once with a config equal to `frozen_config()`,
plus `split == "dev"` so maintenance cannot quietly re-spend the test split.

## Acceptance criterion 7 tested one row, not two

The criterion: *"Two run dirs, one old and one new, both appear in the
regenerated table with their own `corpus` cells — old rows survive
regeneration."* `test_results_regeneration_is_idempotent` builds **one** run
directory and asserts `first == second`. Rendering the same single row twice
is idempotence; it is not survival, which is the property the task exists to
guarantee — a re-run against a moved corpus must not restate the old numbers
as though they had been measured on the new one.

I wrote the claim into the first draft of this document before checking it,
and it was false. The test now builds two run directories of different
vintages, asserts both rows are present, and asserts each carries its own
truncated digest and that the two differ.

## The unknown-is-not-zero rule, four more times

`decisions/0020` named the rule and `decisions/0021` found four violations.
Four more here:

| was | now |
|---|---|
| `detail["changed_count"] = len(changed_urls)` — and `changed_urls` is capped at 50, so the count under-reported at exactly the point the news got worst | the true count; the capped list is named a sample and the cap is a named constant |
| `published_url_count: len(published_urls) if published_urls else 0` — a lock nobody could read reported **0 urls**, which reads as an empty corpus | `None`, and separately `None` for every count that depends on it |
| A maintenance row with a missing or unrecognised `exit_code` fell through to `alerts_open = False` | `None` plus an `undetermined` sentence. "No alert is open" is a claim about four checks having run and found nothing |
| An exit-2 row listing no fired alert read as `alerts_open = False` | `None`: T34 exits 2 only when something fired, so a row disagreeing with itself is untrustworthy, which is not the same as nothing being wrong |

## The test split, unlocked by an empty string

`frozen_config(split="test", license_test_split="")` was permitted and logged
nothing:

```python
    if split == "test" and license_test_split is None:
        raise ValueError(...)
    if split == "test" and license_test_split:   # "" is falsy -> no log
        _log_test_access_for_maintenance(license_test_split)
```

An empty string is not `None`, so the guard passed; an empty string is falsy,
so the logging was skipped. The standing rule is that a test-set read which was
not logged did not happen, and this path spent the split while writing no row.

**Resolved:** a blank or whitespace reason is refused along with a missing one.

### And the hash in the access log was always `None`

```python
split_lock = load_split_lock(Path("data/gold/split.lock"))
split_hash = split_lock.digest if split_lock else None
```

`load_split_lock` returns a plain `dict` (`mcrag/eval/gold.py:141`), so
`.digest` raises `AttributeError` on every call — swallowed by a bare
`except Exception: pass` directly above. Every access row this would ever have
written said `split.lock hash: None`. The access log exists to identify *which*
split was spent; the one field that does that was structurally dead.

`scripts/run_t22b_test_confirmatory.py` reads it correctly as
`split_lock["split_hash"]`, in the file the brief pointed at as the format to
match.

**Resolved:** read by key, with the exception types narrowed. A genuinely
unreadable lock now logs `unresolved (<type>: <reason>)` rather than `None` —
the access still happened and still gets a row, but the row says the hash could
not be established instead of leaving a reader to guess whether anybody looked.

## Smaller things

- `TriggerDecision`'s docstring said *"non-empty `undetermined` still sets
  `fires=False` so the process exits with code 3 instead of 2"* — which the
  code does not do and D9 forbids. An open alert fires while a missing
  published lock stays undetermined; that case exits 2 and reports both. A
  reader trusting the docstring would have believed the opposite.
- `append_trigger_log` created its parent directory *before* validating the
  timestamp, so a rejected call left a directory behind. Checked first now.
- A corrupt lock and an absent one both produced the sentence "the published
  lock has zero URLs". They are different repairs and the log row is all a
  reader gets, so they are now different sentences.
- Each lock was opened and parsed twice (once for urls, once for the snapshot
  hash). One read now.
- An unused `import json` was added to `scripts/generate_results.py`, and
  `tempfile` and `Config` were imported unused by the test file.
- D13 requires `?` for a run with no `corpus.lock`, "never a blank or a dash".
  Every one of the 60 run directories has a `corpus.lock`, so no published row
  exercises that branch — which is exactly why it needed a test, and had none.

## Decisions I made that the brief did not cover

Reported here rather than absorbed, which is the part the last two agents got
wrong:

1. **`_default_rerun_fn` raises.** Argued above. The brief said the executor is
   injected and no test may call a real one; it did not say what the default
   should be, and "nothing" was the wrong answer.
2. **A maintenance row with an unrecognised or missing exit code is
   `undetermined`.** D7 enumerated exit 0, 1, 2 and the missing-log case. A row
   carrying exit code 7, or no exit code at all, is not in that list; by the
   governing rule it is unknown, not clean.
3. **An exit-2 row that lists no fired alert is `undetermined`.** D7 said
   `True` on `exit_code == 2` *or* any fired alert. Taken literally, a
   self-contradicting row would have fired the trigger and spent quota on a
   row that cannot be trusted to mean anything. Treating the contradiction as
   unknown is the same rule applied one level up.
4. **An unreadable `split.lock` logs `unresolved (...)` and proceeds** rather
   than refusing a licensed access. A human licensed the spend; refusing on a
   missing provenance file would block the thing they authorised, while a row
   naming what could not be read stays accountable.
5. **`data/maintenance/published_corpus.lock` is committed.** `indexes/` is
   gitignored as a build artifact, so the published lock is the only surviving
   record of which corpus the published numbers were measured against. A fresh
   checkout therefore has a published lock and no live one, which reports
   `undetermined` and exit 3 — correct: build the index first.

## The same defect, in my own rewrite

The fix for the agent's three-valued alert read was mine, and nobody reviewed
it. Reading it back found the defect it exists to prevent, inside the function
written to prevent it.

`_alerts_open` collected the fired alerts with `a.get("fired")` across the list
and answered `False` when none came back truthy. I probed it rather than
reasoning about it, and five separately malformed rows all returned
`(False, None)` — measured silence:

| the row | read as |
|---|---|
| two of the four checks present | no alert is open |
| an **empty** alert list | no alert is open |
| an entry with no `fired` key | that check ran and found nothing |
| `"fired": "no"`, a string | that check ran and found nothing |
| a non-dict entry in the list | skipped; answer taken from the rest |

The empty list is the one that matters. `decisions/0021` is about four alert
instances three of which could not fire; this is a reader of their output
treating a row carrying *zero* verdicts as all four having run and found
nothing. `append_maintenance_log`'s own docstring calls the argument "list of
all four Alert records" — the completeness was documented and never checked.

"No alert is open" is now a claim about the whole set: every entry must be a
dict with a string name and a **boolean** verdict, every check must have
reported, and the exit code must agree with the verdicts. Anything else is
`undetermined`, which is exit 3.

### One source of truth for what "all the checks" means

The count had to come from somewhere, and hardcoding four in the trigger would
have been the same bug with a longer fuse: a fifth check added to `alerts.py`
would leave every five-check row reading as complete while one verdict went
unexamined. `ALL_CHECKS` and `ALL_CHECK_NAMES` are new in `alerts.py`,
`run.py` builds its checks from the tuple instead of naming the four by hand,
and the trigger counts against the names. A test asserts the two agree and
that `run.py` has not gone back to rebuilding the list beside the canonical
one.

### Two smaller ones

`_read_last_maintenance_log` did not catch `OSError` while `_read_lock` did,
so a permission error on the maintenance log crashed the run to exit 1 while
the same error on a corpus lock exited 3 — two different events for a reader,
with nothing to tell them apart. `_alerts_open`'s docstring already claimed it
reported "unreadable" as unknown. It does now, for both files.

And the fired alert names were computed and thrown away. The reason sentence
read "A T34 maintenance alert is open on the last run" and sent the reader to
another file to learn which one, in a module whose stated premise is that the
logged row is the only diagnosis they get. The names are now in the sentence
and in `detail["fired_alerts"]` — which is `None`, not `[]`, when the status is
unknown, because `[]` would say the checks ran and none of them fired.

### Decisions in this round the brief did not cover

6. **A row whose exit code disagrees with its own verdicts is `undetermined`
   in both directions.** Decision 3 above covered exit 2 beside nothing fired.
   The mirror — exit 0 beside a fired alert — is equally impossible for T34 to
   have written, and equally untrustworthy.
7. **Completeness is measured against the canonical check set, not a literal
   four.** A row missing any check that currently exists is refused, so adding
   a fifth check correctly invalidates rows written before it existed. That is
   the intended reading: those rows carry no verdict from the new check, and
   the trigger should say so rather than assume it would have passed.

## Verification

Eighteen mutations, each reverted after, each caught:

| mutation | caught |
|---|---|
| threshold moved off 10% | yes |
| fires on `>=` instead of `>` | yes |
| `changed_count` reports the capped sample | yes |
| a missing lock reports 0 urls instead of `None` | yes |
| an unmeasured `changed_count` is written as `0` | yes |
| an exit-1 row is read as alerts-having-run | yes |
| an exit-2 row with no fired alert reads as silence | yes |
| an unrecognised exit code reads as silence | yes |
| the naive-timestamp guard is removed | yes |
| the default executor goes back to a no-op | yes |
| a failed re-run exits 2 instead of 1 | yes |
| the re-run receives a config that is not the frozen one | yes |
| a blank license unlocks the test split | yes |
| the split hash is read as an attribute again | yes |
| an unreadable split lock logs `None` | yes |
| a run with no `corpus.lock` renders a blank instead of `?` | yes |
| the digest is truncated to 8 characters instead of 16 | yes |
| the corpus digest is never read from the run dir | yes |

One was not caught on the first pass: disabling the exit-1 branch left the
"unrecognised exit code" guard to catch it, so `alerts_open` was still `None`
and the test — which asserted only `is None` and a non-empty `undetermined` —
still passed. For an exit-1 row the *reason* is the whole diagnostic, so that
test now asserts the sentence names the chain failure.

**The first run of the mutation script was itself void** and said 16/16. It
passed pytest a test path that does not exist (`tests/test_task35_stale_gold.py`);
pytest exits non-zero on an unknown path, so every mutation read as "caught"
regardless of the mutation. A verifier that cannot fail is the subject of this
document, and it took a second look to notice it in my own tooling. The table
above is from the re-run against real paths, with an unmutated control
confirming exit 0 first.

### The second round, against my own fixes

Fourteen more mutations, control first, each caught:

| mutation | caught |
|---|---|
| the incomplete-verdict-set guard never fires | yes |
| completeness measured against the row instead of the canonical set | yes |
| a non-boolean `fired` is accepted as a verdict | yes |
| a missing `fired` key is coerced to not-fired | yes |
| a non-dict alert entry is skipped instead of rejected | yes |
| the exit-0-but-fired disagreement is ignored | yes |
| the exit-2-but-nothing-fired disagreement is ignored | yes |
| `OSError` on the log read escapes again | yes |
| `fired_alerts` is `[]` rather than `None` when the status is unknown | yes |
| the reason sentence stops naming which alert fired | yes |
| the incomplete sentence stops naming the missing checks | yes |
| the run rebuilds its check list by hand beside the canonical one | yes |
| `ALL_CHECKS` loses a check, so the run stops performing it | yes |
| `ALL_CHECK_NAMES` is derived from something other than `ALL_CHECKS` | yes |

The control ran before anything was mutated and had to exit 0, which is the
lesson from the void run above. It also earned its keep twice: the assertion
added after that run — that every test path exists before the script does
anything — caught a *second* wrong path in this script
(`tests/test_task34_maintenance.py`; the file is `test_task34_alerts.py`)
before a single mutation had been applied.

### The trigger, run for real

`scripts/run_rerun_trigger.py` against the actual repo rather than a fixture:
**exit 3**. The published and live `corpus.lock` carry the same snapshot hash
over the same 1699 urls, so the corpus condition is a measured 0.0% — but no
maintenance run has ever been logged, so the alert condition cannot be
established. The logged row carries `alerts_open: null` and
`fired_alerts: null`, not `[]`. This is the first time an exit code from this
task has been produced by real inputs, and it is the one the task exists for:
**T34 shipped and has never executed**, and the trigger says so rather than
reading it as silence.

Full suite: **843 passed** (801 after T34, 42 of them this task).
`RESULTS.md` regenerated: 60 rows, every one carrying a `corpus` cell, no
blanks. `node clients/verify_chat_client.mjs`: 11 checks passed. `notes.md`
unmodified by the suite, and `data/maintenance/` holds only the published lock.

## What this does not claim

**No re-run has ever been executed.** `_default_rerun_fn` raises, by the
reasoning above, so every exit-2 path in this repo has been driven with an
injected stub. What is verified is the decision, the exit code, the logged row,
and the config the executor receives. What is not verified is a re-run
producing a run directory, and therefore a new `RESULTS.md` row has never
appeared by this route — the "old rows stay" half of the criterion is verified
structurally (the table is regenerated wholesale from `runs/`, and a test
asserts two run directories of different vintages both survive with their own
`corpus` cells), not by observing a real re-run land.

**Nothing is scheduled.** T34 was the entry point and the exit codes; T36 is
the trigger and the exit codes. No crontab is installed by either, and
`decisions/0019`'s accounting of what Phase 7 ships without stands.

**`published_corpus.lock` is published by `scripts/generate_results.py`**, so
it tracks whatever corpus was live when someone last ran that script. It is
correct by construction only if `RESULTS.md` is never hand-edited, which the
file's own first line already requires.
