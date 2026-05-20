# Bolt Handoff: Baseball brAIn Enterprise Run Saving Tool

## Objective

Create a new clean enterprise frontend for MLB clubs. Do not reuse live trading UI or mention Kalshi, wagers, markets, bankroll, or trade logic.

The product is a `Run Saving Tool`.

Primary user promise:

> Make a club a little smarter about pitcher allocation decisions by identifying defensible preventable run risk in pitcher deployment choices.

## Core User Workflows

1. Review today's highest-value preventable-run pitcher decisions.
2. Inspect a pitcher trajectory to see whether he is decaying, stabilizing, or recovering.
3. Compare the current starter to available bullpen alternatives.
4. Audit yesterday's pitcher changes and quantify preventable run risk.
5. Identify Triple-A short-window arms who may be useful MLB relief conversion candidates.
6. Generate a daily team brief.

## Design Requirements

Use the deck-inspired design system:

- Navy background.
- Gold accents.
- White cards.
- Pale blue analytical cards.
- Serif headlines.
- Mono metric labels.
- No sportsbook/trading visual language.

## Model Language

Use continuous dynamic decay, not hard bucket identities.

Good:

- `Current trajectory: Settling/recovering, 72% confidence`
- `Projected preventable runs: +0.42`
- `Hold starter: relief alternative does not clear preventable-run threshold`
- `Prepare bullpen: cliff probability rising over next pocket`

Avoid:

- `This pitcher is definitely a settler`
- `Always pull after inning 3`
- `Guaranteed run prevention`

## Triple-A Language

Triple-A is a player-allocation discovery surface, not a prospect-ranking board.

Good:

- `2-inning MLB relief candidate`
- `Strong short-window signal, medium confidence`
- `Mirage risk elevated due to small sample`
- `Scout review recommended before promotion`

Avoid:

- `Guaranteed MLB reliever`
- `Best Triple-A prospect`
- `Promote immediately`

## Frontend Pages To Build First

This scaffold starts with a dashboard prototype. Expand into:

- `Run Saving Board`
- `Triple-A Conversion Board`
- `Staff Fingerprints`
- `Pitcher Profile`
- `Bullpen Alternative Board`
- `Game Replay`
- `Postgame Audit`
- `Daily Brief`

## Preview Rule

Do not wire dummy, mock, or fallback player records.

Set this environment variable in Bolt:

```text
VITE_BASEBALL_BRAIN_API_BASE=https://aroncm--abs-challenge-api-tuned-fastapi-app-tuned.modal.run
```

If the backend is unavailable, show the configured empty/error state. Do not replace it with fabricated data.

## Backend Direction

Reuse current Baseball brAIn backend artifacts first:

- Pitching summary.
- Pitching games catalog.
- Pitch-by-pitch replay artifacts.
- Pitching recap artifacts.
- Mound Audit summary.
- Reliever RSS.

Then add enterprise-specific API adapters:

- `/v1/enterprise/run-saving/board`
- `/v1/enterprise/run-saving/staff`
- `/v1/enterprise/run-saving/decisions`
- `/v1/enterprise/run-saving/pitcher/{pitcher_id}`
- `/v1/enterprise/run-saving/game/{game_id}/audit`

The first local adapter has been added to `infra/modal/app.py`:

```text
GET /v1/enterprise/run-saving/board?league=mlb
```

Current scope:

- Real pitcher decision windows from pitching audit artifacts.
- Real top bullpen alternative from the existing bullpen option artifact.
- Real postgame audit cases from delayed hook, missed hook, justified stay, and bullpen-thin windows.
- `Projected Preventable Runs` is calibrated when comparable historical windows exist.
- Triple-A conversion candidates remain empty until the translation layer is built.
