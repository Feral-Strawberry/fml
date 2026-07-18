# Rankings: pairwise comparison with arenas (ranking module)

> What is this? An **optional module** (default: off) that builds rankings
> **in addition to the star rating** — via pairwise comparison like on
> LMArena: two media from a self-defined **arena**, you click the better
> one, and an Elo leaderboard emerges in the background. Side effect:
> gamification and rediscovery of old material — the pair selection makes
> sure every image gets its turn eventually.

## Enabling

The module is off out of the box and then costs nothing (no sidebar group,
no queries). To enable:

- **Admin → Configuration → Modules → "Ranking module (arenas & duels)"**
  — tick and save; takes effect immediately, no restart. Or:
- in `config.toml`: `[rankings]` → `enabled = true`.

The sidebar group **"Rankings"** then appears on the left.

## Arenas

An **arena** is a named ranking over a subset of the library: **name +
filter expression** (the same grammar as the search box, e.g.
`tag: portrait` or `model: "flux"` — empty = whole library). The
population is evaluated **live**, like saved searches: newly imported
media grow into it automatically, rejected media fall out.

- **Create:** sidebar → Rankings → "+ New arena" (name + expression).
- **Rename / change population:** the ✎ in the arena view — existing
  duels are kept.
- **Delete:** **Admin → Maintenance → Ranking arenas**, two-step —
  deletes the arena **with all duels and scores**. (The ✕ in the arena
  view only closes the view, as everywhere else.)

The counter on the arena row is the current population; the duel count so
far is in the tooltip.

## Leaderboard (default view)

Clicking an arena opens the **leaderboard** as a large view: on the left
the medium of the current rank, below it placement, Elo and duel count; on
the right the ranking (rank, thumbnail, Elo) as a **scrolling column** —
at rank 55, the neighborhood ~50–60 stays visible. Best score first; items
without a duel do not appear (no rank without a verdict).

- `←`/`→` (or `↑`/`↓`) pages in **rank order** — that is how you click
  through the arena's gems. `Home`/`End` jumps to the first/last rank.
- Clicking in the column jumps to that rank; the column loads more as you
  scroll.
- `Enter` (or the button at the bottom) opens the **single view** with all
  metadata — e.g. to pull out the prompt; `Esc` there leads back to the
  arena.
- If the list is still empty, a button leads straight into the first duel.

## Duel mode

The toggle at the top switches to duel mode: two media side by side
(videos loop muted).

- **Click the better one** (or `←`/`→`) scores the duel — the new Elo
  briefly appears at the pair, then the next one comes up.
- **Both lose** (button or `↓`): both are bad — both get a duel and lose
  points (as if they had lost against an average image). Important against
  returners: the pair counts as compared and does not keep coming back.
  This is a ranking verdict, not a way to sort out — rejecting still
  exists for that.
- **Skip** (button or space) is the honest "don't know / pair doesn't
  fit": **nothing** is scored and nothing is stored.
- `Esc` closes the view.

The pair selection follows "coverage, then proximity": items with the
fewest duels come up preferentially (every image gets rediscovered), and
the opponent preferentially comes from the Elo neighborhood (close duels
are the most informative).

## How the scores work (and why nothing is ever lost)

Every **duel** is stored (who won against whom, when) — that is the raw
truth and is never modified. The **Elo score** (start 1000, K-factor 32)
is merely derived from it and reproducible at any time: **Admin →
Maintenance → "Recompute ranking scores"** replays the entire duel log
deterministically (re-scan principle). If an item disappears from the
library (rejected/moved out), its duel history is kept — it just no longer
appears in pairs or on the leaderboard.

Background and decisions: ADR 0045 (German).
