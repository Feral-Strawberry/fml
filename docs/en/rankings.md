# Rankings: pairwise comparison with leaderboard (ranking module)

> What is this? An **optional module** (default: off) that builds rankings
> **in addition to the star rating** — via pairwise comparison like on
> LMArena: two media from a self-defined **ranking**, you click the better
> one, and an Elo leaderboard emerges in the background. Side effect:
> gamification and rediscovery of old material — the pair selection makes
> sure every image gets its turn eventually.

## Enabling

The module is off out of the box and then costs nothing (no sidebar group,
no queries). To enable:

- **Admin → Configuration → Modules → "Ranking module"** (switch "Enable
  rankings & duels") — tick and save; takes effect immediately, no restart. Or:
- in `config.toml`: `[rankings]` → `enabled = true`.

The sidebar group **"Rankings"** then appears on the left.

## Creating and maintaining rankings

A ranking is the third step of search → saved search → ranking (the
interaction model is explained in
[gui.md](gui.md#search-saved-search-ranking-one-idea)).
A **ranking** is a named subset of the library that duels run over: **name +
filter expression** (the same grammar as the search box, e.g.
`tag: portrait` or `model: "flux"` — empty = whole library). The
population is evaluated **live**, like saved searches: newly imported
media grow into it automatically, rejected media fall out.

- **Create:** click the population together in the gallery (sidebar,
  "+ Criterion", chips), then **🏆 Ranking** next to the ☆ in the chip bar.
  The dialog shows the chips as a preview with the hit count and only asks
  for the name; without chips the population is the whole library. A
  `sort:` chip is not taken over, the ranking has its own order. If you
  prefer typing: unfold "Type the expression yourself" in the dialog,
  Enter checks the expression and shows it as chips. After creating, the
  ranking opens.
- **Rename / change population:** the ✎ in the ranking view (or "Edit"
  per row on the admin page "Rankings"). It closes the ranking and loads
  its population as chips into the gallery; the breadcrumb
  switches to edit mode (accent-tinted, **"Editing: 🏆 Name"**, sidebar
  row highlighted, buttons on the right as symbols only) with ✎ (rename),
  **Save ranking** (only active when the chips differ, a dot then marks
  the name) and **✕ Stop editing**. Change chips as usual; Save ranking
  leads back into the ranking, Stop editing goes back without saving. Existing duels are kept.
- **Delete:** **Admin → Rankings**, with a confirmation dialog — deletes
  the ranking **with all duels and scores**. Deliberately only there: an
  accidentally deleted saved search is quickly clicked together again, a
  deleted ranking takes thousands of duels with it. (The ✕ in the ranking
  view only closes the view, as everywhere else.)

The counter on the ranking row is the current population; the duel count so
far is in the tooltip.

## Leaderboard (default view)

Clicking a ranking opens the **leaderboard** as a large view: on the left
the medium of the current rank, below it placement, Elo and duel count; on
the right the ranking (rank, thumbnail, Elo) as a **scrolling column** —
at rank 55, the neighborhood ~50–60 stays visible. Best score first; items
without a duel do not appear (no rank without a verdict). **Items that
are out** (see "Both out") sit dimmed and grouped at the **end** of the
column, with the marker "out" instead of a rank number; the ranking header
counts them ("… · 12 out"). What you sorted out stays visible.

- `←`/`→` (or `↑`/`↓`) pages in **rank order** — that is how you click
  through the ranking's gems. `Home`/`End` jumps to the first/last rank.
- Clicking in the column jumps to that rank; the column loads more as you
  scroll.
- `Enter` (or the button at the bottom) opens the **single view** with all
  metadata — e.g. to pull out the prompt; `Esc` there leads back to the
  ranking.
- When an item that is out is shown on the left, the info line says
  "Out of this ranking" and offers **Back in**: the item returns to this
  ranking's pool, Elo and duel count stay. The list reloads and stays at
  the same position, where the next item that is out now sits, so the
  tail of the list can be reviewed quickly.
- If the list is still empty, a button leads straight into the first duel.

## Duel mode

The toggle at the top switches to duel mode: two media side by side
(videos loop muted). Above each medium sits a header line as in the
compare view: primary location (full path, the tooltip shows it
untruncated), dimensions and container, the **rating dots** (click sets
stars, the same number clears) and **out**. The header is not a judging
area, the path can be selected and copied.

- **out** (button in the header): ends the duel like a click on the other
  image (the partner wins, this one loses points), and this medium also
  leaves the ranking, it never comes up here again. Way back via the
  leaderboard as before.

- **Click the better one** (or `←`/`→`) scores the duel — the new Elo
  briefly appears at the pair, then the next one comes up.
- **Both out** (button or `↓`): both are bad. Both get a duel, lose
  points (as if they had lost against an average image) **and are out of
  this ranking**: they never come up in a duel of this ranking again, with
  any partner. On the leaderboard they sit dimmed at the end; from there
  **Back in** returns them to the pool. This applies to this ranking only
  and is not a way to sort out of the catalog, rejecting still exists for
  that.
- **Skip** (button or space) is the honest "don't know / pair doesn't
  fit" (or "both are great, I can't decide"): **nothing** is scored and
  nothing is stored.
- With fewer than two active items left, duel mode shows "No pairs left:
  n of m items are out" and a button to the leaderboard instead of a pair.
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
deterministically (re-scan principle); whether an item is out is derived
from the log as well ("Both out" sets it, "Back in" lifts it, the last
line counts). If an item disappears from the
library (rejected/moved out), its duel history is kept — it just no longer
appears in pairs or on the leaderboard.

Background and decisions: ADR 0045 (German; there and in the code a
ranking is called an "arena", after LMArena; since ADR 0081 the UI
consistently says "ranking").
