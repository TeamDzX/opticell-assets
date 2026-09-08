# opticell-assets

Generated visual assets for the Opticell marketing site (home.html). Hot-linked via raw.githubusercontent.

- `hero-backdrop.jpg` — manifesto/section backdrop
- `accent-vision.jpg` — Vision section orb
- `accent-toolkit.jpg` — MyLLM toolkit accent
- `accent-cta.jpg` — closing CTA horizon glow
- `headervideo.mp4` — home.html header loop (1284x716, 8s, muted, faststart) + `headervideo-poster.jpg`
- `icon-egrid.png` — E-Grid app icon, 1024x1024 (new letterform format)
- `reverie-topheader.mp4` / `reverie-header.mp4` — Reverie (Damask) landing page bands, 1280x720, 8s, muted, faststart
- `appsheader.mp4` — apps.html header loop (1280x720, 18s, muted, faststart) + `appsheader-poster.jpg`

Apple-keynote style, deep-black + indigo/violet palette. Generated via self-hosted ComfyUI / Flux 2.

---

## `content.json` — dynamic copy for home.html (generated, do not hand-edit)

The dated **"from the workshop"** strip under the hero, plus refreshed body
copy for the seven manifesto cards. Written by `tools/build_content.py`, run
every morning by `.github/workflows/daily-content.yml`.

**The model never runs in the visitor's browser.** home.html is served inside a
public Wix iframe, so anything in that page — a bearer token very much
included — is readable by every visitor via View Source. So `jarvis:26b` is
called here, on our own server, and the result is published as this static file
which home.html fetches unauthenticated. Same arrangement as E-Grid's
`digest.json`, for the same reason.

```bash
MYLLM_KEY="..." python3 tools/build_content.py   # the real thing
python3 tools/build_content.py --no-llm          # templated prose, no server
python3 tools/build_content.py --dry-run         # print it, write nothing
python3 tools/build_content.py --no-principles   # strip only, leave the manifesto alone
```

**Always `--dry-run` first.** The guards catch commercial and factual errors,
not flat writing — read the prose before it replaces what is live.

### What runs when

`.github/workflows/daily-content.yml` runs at **07:40 UTC daily**, and commits
`content.json` straight to `main` if it changed. Nobody needs to run anything
by hand.

**Why 07:40 and not earlier.** The LLM box is offline until 07:00, and GitHub's
cron is fixed to UTC — it does not follow British Summer Time. So the slot has
to clear 07:00 *UTC*, not 07:00 local: 07:40 UTC is 08:40 BST in summer and
07:40 GMT in winter, safely after the server is up either way. If the server's
hours change, move this — and remember that "7am" in London is 06:00 UTC for
half the year.

| | Strip | Principles |
|---|---|---|
| Daily schedule | regenerated | **carried forward untouched** |
| Run workflow, "Regenerate principles" ticked | regenerated | regenerated |
| Run workflow, unticked | regenerated | carried forward |

The seven principles are reviewed brand copy. The guards below catch a *false*
claim, but nothing catches copy that is merely weaker than what it replaced —
so a new manifesto every morning that nobody has read is not worth the
freshness. Regenerating them is a deliberate act: tick the box, then read the
diff on the resulting commit before you leave it up.

Two GitHub facts worth knowing: scheduled workflows only run from the **default
branch**, and GitHub **disables the schedule after 60 days of no repo
activity** — the daily commits keep it alive, but a long quiet spell needs the
schedule re-enabling in the Actions tab.

### Where the facts come from

Apple's own lookup endpoint for developer `1883824295` — every app on the
account, with its live version, release date and the release notes Alex
already wrote. The model is given those and nothing else, so the strip cannot
announce a release the App Store has not published. It never sees a roadmap.

### What is checked before anything ships

Copy that fails a check is thrown away and the template stands in — an idea
lifted from E-Grid, where an item reading like a result for a series whose
podium was never supplied is discarded.

| Check | Why |
|---|---|
| `<think>` blocks and orphan `</think>` stripped | The jarvis fine-tunes emit chain-of-thought even when `think: false` is sent, and sometimes drop the opening tag. The reasoning is full of braces and would break the JSON parse. |
| Pricing claims | Since 14 Jul 2026 every app is free to download **with** a cheap subscription and a lifetime buy-out. "No subscriptions", "free forever", "no in-app purchases" are all false and are exactly what a model reaches for when writing about honest pricing. Any body making one is dropped. |
| Version numbers | A version in the copy must be one we supplied. Catches the most embarrassing error the strip could make. |
| Free-tier overclaims | The subtler version of the pricing error, and the one that got through the first live run: not "there is no subscription" but "the free download gives you everything". A sentence offering full access at no cost is dropped unless it also names what you pay for — so "free to download, then subscribe to unlock everything" survives. |
| Length | Keeps the layout from breaking on a phone. |

### Each principle has a brief

`PRINCIPLE_BRIEFS` in the generator states what each of the seven cards is
*about*. Without them the model writes seven variations on "our pricing is
fair" — the first live run turned "Transparent Pricing" into a restatement of
"Optional Upgrades", leaving two of the seven cards saying the same thing.
Change a card's subject there, not in the prompt.

### Failure is designed in

Every failure path leaves the page exactly as it shipped:

- Server down, bad token, non-JSON reply → **the last edition's copy for that
  exact app and version is reused**, and only a release nothing has ever been
  written about falls back to a template. An outage costs the page nothing, and
  cannot quietly replace approved prose with "X 4.3.1 is live on the App Store".
  The run summary says which writer was used, so a server that stays
  unreachable is visible rather than silent.
- A principle the model got wrong → omitted here, so home.html keeps its own copy.
- Fetch fails in the browser, or `raw.githubusercontent` is down → jsDelivr is
  tried, then the strip stays hidden.
- Nobody ran the job for ten days → the edition expires and the band hides,
  rather than boasting about a release from last month.

The strip renders **nothing** unless a live edition is found, so it can only
ever add to the page.

### Editing home.html

home.html lives in `~/Desktop/Opticell` and is pasted into Wix by hand — this
repo does not serve it. Changing what the strip looks like means editing that
file and re-pasting it. Changing what it *says* means only this file, which
needs no Wix step at all.
