# Daily Real-Machine Validation

This runner is the real-machine gate for the DailyTask, Coffee, and Gift safe
paths. It writes all screenshots, traces, and result JSON under `working/`, which
is ignored by git.

## Commands

```powershell
uv run python .\scripts\run_daily_real_validation.py --mode daily-full --json
uv run python .\scripts\run_daily_real_validation.py --mode coffee-only --json
uv run python .\scripts\run_daily_real_validation.py --mode daily-task-only --json
uv run python .\scripts\run_daily_real_validation.py --mode gift-only --json
```

PowerShell wrapper:

```powershell
.\scripts\run_daily_real_validation.ps1 -Mode daily-full -Json
```

Each run creates:

```text
working/daily_real_validation_<YYYYMMDD_HHMMSS>/summary.json
```

## Modes

`daily-full` runs:

- coffee income claim
- coffee supply purchase
- coffee product optimization
- Gift task-item validation; if the daily task is already consumed, Gift
  real-send validation is reported separately by `gift-only`
- daily activity panel recognition
- completed daily activity card claim
- daily activity milestone claim when the existing DailyTask rules allow it
- mail reward claim
- battle-pass periodic mission-page claim, then reward-track claim

`coffee-only` runs the coffee path: open one-cafe, claim income, optimize
products, and replenish supply.

`daily-task-only` runs only the DailyTask safe path: activity recognition,
completed card claims, allowed milestone claims, mail, and periodic rewards.

`gift-only` validates a real default-character/default-gift send. It first tries
the F1 daily task item path so a `1/1` Gift task reward can be claimed after the
send. If the daily task state is already consumed, it opens the phone menu,
clicks the OCR-detected `羁遇` entry, sends one default visible gift, and records
`daily_task_state_unavailable_because_already_consumed`.

## Safety Rules

Allowed mutations are limited to mail rewards, periodic rewards, daily activity
rewards, coffee income, coffee supply, coffee product optimization, and the
explicit `gift-only` default Gift real-send validation. The runner does not use
fixed global coordinates for Gift entry: the phone-menu fallback clicks the
OCR-detected `羁遇` evidence box and verifies the Gift page before sending.

Daily activity rewards are intentionally claimed after the safe task paths have
run. Battle-pass periodic rewards are also split in order: first the mission
page is opened and visible task-row `领取` controls are clicked only when OCR
identifies them, then the reward track is opened and the bottom `全部领取`
control is clicked only after that.

Coffee product optimization is only considered successful when the full
replacement completes. A failed half-step such as `deselect_product:*` followed
by a missing `select_product:*` is reported as a failure and the deselect action
is still recorded as `mutation_performed=true`.

The product list scan scrolls through multiple pages before ranking candidates,
then resets the list back to the top before clicking. This prevents the runner
from ranking only the initially visible products and missing higher-priced
items at the bottom of the unified product editor.

Coffee supply treats the in-game missing-material prompt as part of the supply
path: the runner clicks `送货上门`, clicks the follow-up `确认`, waits through the
delivery challenge/result when that flow is opened, and records the final supply
purchase only after the shop reports success. If the run starts on a pending
delivery confirmation or challenge result, it finishes that coffee delivery path
instead of abandoning the validation mid-flow.

If `HTGame.exe` is not running or the game window cannot be captured, the runner
does not fake success. It writes `window_not_found` and returns a non-zero exit
code. Permission and PostMessage failures are recorded as `permission_denied` or
`postmessage_failed`.

No claimable activity reward and already-full or already-optimal coffee states
are reported as skips with reasons; they do not count as failures when the
underlying module reports a safe skip.
