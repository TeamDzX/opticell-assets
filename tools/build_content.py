#!/usr/bin/env python3
"""Builds the dynamic copy that home.html shows, written into `content.json`.

Same shape as E-Grid's `digest/build_digest.py`, and for the same reason: the
model never runs in the visitor's browser. It runs here, against facts we
already hold, and the result is published as a static JSON file that home.html
fetches unauthenticated. home.html sits in a public Wix iframe, so a bearer
token in that page would be a bearer token on the open web.

Two blocks are generated:

  workshop    a dated "from the workshop" strip under the hero: a one-line
              intro plus one line per recently-updated app. The facts come
              from Apple's own lookup endpoint for developer 1883824295 --
              version numbers, release dates and the release notes Alex
              already wrote. The model never sees a roadmap and cannot
              announce something that has not shipped.

  principles  refreshed body copy for the seven manifesto cards. The static
              copy in home.html is the fallback: a principle the model got
              wrong is simply omitted here, and the page keeps what it ships
              with. Nothing is ever blanked.

Both are optional. If the server is down, the token is missing, the reply
isn't JSON or a check fails, the edition still publishes -- with templated
prose for the workshop items and no principle overrides at all. A broken
writer downgrades the writing, never the page.

Usage:
    MYLLM_KEY="..." python3 tools/build_content.py
    python3 tools/build_content.py --no-llm      # templated prose only
    python3 tools/build_content.py --dry-run     # print, do not write
    python3 tools/build_content.py --days 90     # widen the window
    python3 tools/build_content.py --no-principles   # strip only, leave the
                                                     # manifesto copy alone

Env:
    MYLLM_KEY     bearer token for the server -- REQUIRED for prose, never hardcode
    MYLLM_BASE    default https://optidns.uk
    MYLLM_PATH    default /api/chat   (Ollama-native; /v1/chat/completions also works)
    MYLLM_MODEL   default jarvis:26b
    MYLLM_TIMEOUT default 300 seconds -- a 26B model writing two blocks is not fast

Exit code is non-zero only when nothing at all could be built.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# This script lives INSIDE the opticell-assets repo (as E-Grid's generator
# lives inside egrid-content), so the GitHub Action that runs it and the file
# it writes are versioned together.
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "content.json"

# Apple's own catalogue for the developer account behind every Opticell app.
# This is the fact feed: versions and dates are Apple's, not ours, so the
# strip cannot claim a release the App Store has not actually published.
DEVELOPER_ID = "1883824295"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
STOREFRONT = "gb"

# Editions kept in the file. home.html only ever renders the newest live one;
# the rest are there so a bad run can be compared against what it replaced.
KEEP_EDITIONS = 4

# A strip older than this stops rendering, so a broken cron leaves the band
# hidden rather than boasting about a release from two months ago.
EDITION_TTL_DAYS = 10

# How far back an App Store update counts as "recent", and how many make the
# strip. Three is what the layout holds without wrapping on a phone.
DEFAULT_WINDOW_DAYS = 45
MAX_ITEMS = 3

USER_AGENT = "Opticell-content/1.0 (+https://www.opticell-limited.com)"
TIMEOUT = 20

# The seven manifesto cards in home.html, keyed exactly as `data-modal` and the
# PRINCIPLES object are. A key the model invents is dropped; a key it omits
# keeps the copy home.html ships with.
PRINCIPLE_KEYS = {
    "free": "Free to Download",
    "upgrades": "Optional Upgrades",
    "pricing": "Transparent Pricing",
    "privacy": "No Data Collection",
    "ads": "No Ads",
    "partnership": "Human-AI Partnership",
    "audience": "For Individuals & Businesses",
}

# What each card is actually ABOUT. Without these the model writes seven
# variations on "our pricing is fair": the first run turned "Transparent
# Pricing" into a restatement of "Optional Upgrades", leaving two of the seven
# cards saying the same thing. The brief is the card's subject, not its wording.
PRINCIPLE_BRIEFS = {
    "free": "The download costs nothing and asks for no card details, so you can "
            "judge the app on your own device first. Do NOT claim the free "
            "download gives full functionality -- it does not; that is what the "
            "subscription or the lifetime unlock is for.",
    "upgrades": "The two ways to unlock the full app -- an ultra-affordable "
                "subscription, or a one-time lifetime purchase -- and that both "
                "are opt-in, with the subscription cancellable in Apple or Google "
                "account settings.",
    "pricing": "STRICTLY about prices being VISIBLE before you commit: every "
               "price on the App Store and Google Play product page before you "
               "install, and shown in the app before you buy. No dark patterns, "
               "nothing in the fine print. Do NOT describe the subscription and "
               "lifetime options here -- that is the 'upgrades' card's job.",
    "privacy": "No analytics on usage, nothing sold to advertisers or data "
               "brokers, data stays on the device. Privacy as the default, not a "
               "feature.",
    "ads": "No banners, no interstitials, no sponsored content, no rewarded "
           "video. Make the ARGUMENT: ads compete for attention and push apps "
           "towards harvesting data.",
    "partnership": "Where the apps use AI, it extends what the person can do "
                   "rather than replacing their judgement or mining their "
                   "thoughts. The human stays in charge.",
    "audience": "The catalogue spans personal tools and professional ones, on "
                "the same terms for both. Name a couple of each.",
}

# The commercial model, stated once. Since 14 Jul 2026 every app is free to
# download WITH a cheap subscription and a lifetime buy-out. The old "no
# subscriptions" line is now false, and it is exactly the sort of thing a
# model reaches for when writing about honest pricing -- so it is both in the
# prompt and in the checks below.
PRICING_TRUTH = (
    "Every Opticell app is free to download. Each one offers an ultra-affordable "
    "subscription that unlocks the full app, AND a one-time lifetime purchase for "
    "people who would rather own it outright. Both are opt-in. There are no ads and "
    "no data collection."
)

# Claims that contradict PRICING_TRUTH. A body matching any of these is thrown
# away for the static copy -- the same idea as E-Grid discarding an item that
# reads like a result for a series whose podium was never supplied.
FORBIDDEN_CLAIMS = [
    r"\bno subscription",
    r"\bnever\s+(?:a\s+)?subscription",
    r"\bwithout\s+(?:a\s+)?subscription",
    r"\bsubscription[- ]free\b",
    r"\bno in-app purchase",
    r"\bno recurring\b",
    r"\bfree forever\b",
    r"\bcompletely free\b",
    r"\bentirely free\b",
    r"\bfree,? with no\b",
    r"\bone-?time (?:purchase )?only\b",
    r"\bno (?:hidden )?(?:fees|costs|charges) (?:at all|whatsoever|ever)\b",
    r"\bopen[- ]source\b",
    r"\bwe (?:are|'re) free\b",
]

# The subtler version of the same error, and the one that actually got through:
# not "there is no subscription" but "the free tier gives you everything". The
# free download is a real app you can judge, NOT the full app -- that is what
# the subscription unlocks. A flat pattern list cannot catch this, because
# "a subscription unlocks the full app" is the sentence we WANT.
#
# So: flag a sentence that offers full access at no cost, unless it also names
# the thing you pay for. That keeps "free to download, then subscribe to unlock
# everything" while rejecting "explore the full functionality at no cost".
FULL_ACCESS = re.compile(
    r"\b(?:full (?:functionality|features?|version|app|experience|access)"
    r"|all (?:the )?features|everything|complete access|unrestricted)\b", re.I)
NO_COST = re.compile(
    r"\b(?:free|no cost|without (?:any )?(?:upfront )?cost|at no charge"
    r"|without paying|no upfront|no charge|costs? nothing)\b", re.I)
PAID_TIER = re.compile(
    r"\b(?:subscri\w+|unlocks?|unlocking|upgrade\w*|purchase\w*|buy|bought"
    r"|lifetime|paid|pay for)\b", re.I)


def overclaims_free_tier(text: str) -> str | None:
    """Returns the offending sentence, or None. Errs towards letting copy
    through: a false negative just means a human reads it in --dry-run, which
    happens anyway."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if (FULL_ACCESS.search(sentence) and NO_COST.search(sentence)
                and not PAID_TIER.search(sentence)):
            return sentence.strip()
    return None

MAX_ITEM_CHARS = 220
MAX_INTRO_CHARS = 200
MAX_PRINCIPLE_CHARS = 900
MIN_PRINCIPLE_CHARS = 120


def log(message: str) -> None:
    print(message, file=sys.stderr)


# --------------------------------------------------------------------------- #
# Facts
# --------------------------------------------------------------------------- #


@dataclass
class Release:
    name: str
    version: str
    date: dt.date
    url: str
    notes: str = ""

    @property
    def short_name(self) -> str:
        """"MyLLM - Local AI Agent" is a store listing, not how we say it, and
        neither is "Hanyu: Learn Chinese Mandarin". The dash form needs spaces
        on both sides so "E-Grid" survives; the colon form does not."""
        return re.split(r"\s+[-–]\s+|:\s+", self.name)[0].strip()


def http_json(url: str, timeout: int = TIMEOUT) -> dict | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, json.JSONDecodeError) as error:
        log(f"  {url}: {type(error).__name__}: {error}")
        return None


def fetch_releases(today: dt.date, window_days: int) -> list[Release]:
    """Every app on the developer account, newest update first.

    NOTE: Apple's iTunes caches differ per storefront AND per endpoint -- a GB
    id-lookup has been observed lagging behind the same app's bundleId lookup.
    A version that is a day or two stale here is harmless (the strip just
    describes the previous release); a version that is *ahead* of the store
    would not be, and this endpoint cannot produce one.
    """
    query = urllib.parse.urlencode({
        "id": DEVELOPER_ID, "entity": "software", "limit": 200, "country": STOREFRONT,
    })
    payload = http_json(f"{ITUNES_LOOKUP}?{query}")
    if not payload:
        log("  App Store lookup failed; no releases to describe")
        return []

    releases: list[Release] = []
    for entry in payload.get("results", []):
        if entry.get("kind") != "software":
            continue                                  # the artist row itself
        raw_date = (entry.get("currentVersionReleaseDate") or "")[:10]
        try:
            released = dt.date.fromisoformat(raw_date)
        except ValueError:
            continue
        if released > today:
            continue                                  # clock skew, not news
        releases.append(Release(
            name=entry.get("trackName") or "",
            version=str(entry.get("version") or "").strip(),
            date=released,
            url=entry.get("trackViewUrl") or "",
            notes=clean_notes(entry.get("releaseNotes") or ""),
        ))

    releases.sort(key=lambda r: (r.date, r.short_name), reverse=True)
    cutoff = today - dt.timedelta(days=window_days)
    recent = [r for r in releases if r.date >= cutoff and r.name and r.version]
    log(f"  {len(releases)} apps on the account, {len(recent)} updated since {cutoff}")
    return recent[:MAX_ITEMS]


def clean_notes(notes: str) -> str:
    """Release notes are marketing copy with headings and bullets. The model
    only needs the substance, and a 4,000-character changelog crowds out the
    other two apps in the prompt."""
    text = re.sub(r"\s+", " ", notes).strip()
    text = re.sub(r"(?i)^(what'?s new(?: in [^.]{0,40})?[.—-]?\s*)", "", text)
    return text[:600]


# --------------------------------------------------------------------------- #
# Templates -- what ships when there is no model
# --------------------------------------------------------------------------- #


def template_intro(releases: list[Release], today: dt.date) -> str:
    if not releases:
        return "Steady work across the catalogue this month."
    if len(releases) == 1:
        return f"One update out of the workshop this week: {releases[0].short_name}."
    names = ", ".join(r.short_name for r in releases[:-1])
    return f"Recently out of the workshop: {names} and {releases[-1].short_name}."


def template_item(release: Release) -> str:
    return (f"{release.short_name} {release.version} is live on the App Store, "
            f"released {release.date.strftime('%-d %B %Y')}.")


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = f"""You write short marketing copy for Opticell Ltd, a small \
British software company that makes focused apps for iPhone, iPad, Mac and Android.

House style: plain, confident, specific. British spelling. No exclamation marks, \
no hype words ("revolutionary", "game-changing", "seamless", "cutting-edge"), no \
emoji, no rhetorical questions. Short sentences. Write like a maker describing \
their own work to someone who will use it, not like an advertisement.

Commercial model -- state it correctly or not at all: {PRICING_TRUTH}

CRITICAL: use ONLY the facts you are given. Do not invent features, version \
numbers, dates, app names, statistics, awards or customer quotes. If you are not \
given a fact, write around it. Never claim an app is free of subscriptions or \
in-app purchases; that is false and it is the single worst error you can make here.

Reply with a single JSON object and nothing else. No preamble, no explanation, no \
code fence, no reasoning."""


def strip_reasoning(text: str) -> str:
    """The jarvis fine-tunes emit chain-of-thought even when it is not asked
    for, and sometimes drop the opening <think>, leaving an orphan </think>
    with raw reasoning in front of it. Both shapes have to go before the JSON
    can be found, because the reasoning is full of braces and quotes."""
    text = re.sub(r"<think>.*?</think>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # An orphan close tag: everything before the last one is reasoning.
    if re.search(r"</think>", text, flags=re.IGNORECASE):
        text = re.split(r"</think>", text, flags=re.IGNORECASE)[-1]
    text = re.sub(r"<think>", " ", text, flags=re.IGNORECASE)
    return text.strip()


def parse_json_reply(text: str) -> dict | None:
    """Self-hosted models wrap JSON in a code fence or a sentence often enough
    that this is not defensive programming, it is the normal path."""
    text = strip_reasoning(text)
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    first, last = text.find("{"), text.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    try:
        data = json.loads(text[first:last + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def call_model(user_prompt: str, purpose: str) -> dict | None:
    """One chat turn against Alex's own server. Supports both wire formats:
    Ollama-native (/api/chat) and OpenAI-compatible (/v1/chat/completions),
    because the box serves both and the default differs between projects."""
    base = os.environ.get("MYLLM_BASE", "https://optidns.uk").strip().rstrip("/")
    path = os.environ.get("MYLLM_PATH", "/api/chat").strip()
    model = os.environ.get("MYLLM_MODEL", "jarvis:26b").strip()
    token = os.environ.get("MYLLM_KEY", "").strip()
    timeout = int(os.environ.get("MYLLM_TIMEOUT", "300"))

    if not token:
        log(f"  {purpose}: MYLLM_KEY is not set; falling back")
        return None
    if "://" not in base:
        base = "https://" + base
    if not path.startswith("/"):
        path = "/" + path
    url = base + path

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    openai_shape = path.rstrip("/").endswith("/chat/completions")
    if openai_shape:
        payload = {
            "model": model, "messages": messages, "temperature": 0.4,
            "max_tokens": 3000, "response_format": {"type": "json_object"},
        }
    else:
        payload = {
            "model": model, "messages": messages, "stream": False,
            # think:false is sent but NOT honoured by these fine-tunes -- see
            # strip_reasoning(). Sending it costs nothing and may start working.
            "think": False, "format": "json",
            "options": {"temperature": 0.4, "num_predict": 3000},
        }

    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT,
               "Authorization": "Bearer " + token}
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as error:
        log(f"  {purpose}: {url} returned HTTP {error.code}; falling back")
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        log(f"  {purpose}: {url}: {type(error).__name__}: {error}; falling back")
        return None

    try:
        content = (reply["choices"][0]["message"]["content"] if openai_shape
                   else reply["message"]["content"])
    except (KeyError, IndexError, TypeError):
        log(f"  {purpose}: reply had no message content; falling back")
        return None

    data = parse_json_reply(content or "")
    if data is None:
        log(f"  {purpose}: reply was not JSON; falling back")
        return None
    log(f"  {purpose}: written by {reply.get('model') or model}")
    return data


# --------------------------------------------------------------------------- #
# Checks -- what the model wrote, tested against what it was given
# --------------------------------------------------------------------------- #


def breaks_pricing(text: str) -> str | None:
    """One gate for every commercial claim, so the intro, the item bodies and
    the principles are all held to it."""
    for pattern in FORBIDDEN_CLAIMS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return pattern
    sentence = overclaims_free_tier(text)
    if sentence:
        return f"free tier overclaimed: {sentence!r}"
    return None


def invents_a_version(text: str, allowed: set[str]) -> str | None:
    """A version number in the copy has to be one we supplied. This is the
    cheapest possible hallucination check and it catches the most embarrassing
    error the strip could make -- announcing a release that does not exist."""
    for found in re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", text):
        if found not in allowed:
            return found
    return None


def clean_body(text: object) -> str:
    """Models like to keep the heading, the bullet marker and the quotes."""
    body = str(text or "").strip()
    body = strip_reasoning(body)
    body = re.sub(r"^[\s\-•*#>]+", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > 1 and body[0] in "\"'“" and body[-1] in "\"'”":
        body = body[1:-1].strip()
    return body


def write_workshop(releases: list[Release], today: dt.date) -> tuple[str, list[str]]:
    """Returns (intro, one body per release), templated where the model failed
    or said something that did not survive the checks."""
    intro = template_intro(releases, today)
    bodies = [template_item(r) for r in releases]
    if not releases:
        return intro, bodies

    lines = []
    for index, release in enumerate(releases):
        lines.append(
            f"{index}. {release.short_name} -- version {release.version}, released "
            f"{release.date.strftime('%-d %B %Y')}.\n"
            f"   Release notes: {release.notes or '(none published)'}"
        )
    shape = json.dumps({"intro": "...", "items": [{"index": 0, "body": "..."}]})
    prompt = (
        "Write the 'from the workshop' strip for the Opticell home page.\n\n"
        "These apps were updated on the App Store recently. Everything you may "
        "state about them is here:\n\n" + "\n\n".join(lines) + "\n\n"
        f"Write an 'intro' of ONE sentence, at most {MAX_INTRO_CHARS} characters, "
        "summarising the period without listing every app.\n"
        f"Then write one 'body' per item above, at most {MAX_ITEM_CHARS} characters "
        "each, saying what that release actually changed for the person using it. "
        "Name the app. Do not repeat the version number unless it reads naturally. "
        "Draw only on that app's release notes above.\n\n"
        f"Reply with exactly this JSON shape: {shape}"
    )

    data = call_model(prompt, "workshop strip")
    if not data:
        return intro, bodies

    allowed_versions = {r.version for r in releases}
    for r in releases:                     # "2.1.1" makes "2.1" legitimate too
        allowed_versions.update(re.findall(r"\d+\.\d+", r.version))

    candidate = clean_body(data.get("intro"))
    if candidate and len(candidate) <= MAX_INTRO_CHARS * 2:
        bad = breaks_pricing(candidate) or invents_a_version(candidate, allowed_versions)
        if bad:
            log(f"  dropped the intro: {bad}")
        else:
            intro = candidate

    items = data.get("items")
    by_index: dict[int, str] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            by_index[index] = clean_body(item.get("body"))

    for index, release in enumerate(releases):
        body = by_index.get(index, "")
        if not body:
            continue
        if len(body) > MAX_ITEM_CHARS * 2:
            log(f"  dropped copy for {release.short_name}: {len(body)} chars")
            continue
        bad = breaks_pricing(body)
        if bad:
            log(f"  dropped copy for {release.short_name}: pricing claim /{bad}/")
            continue
        bad = invents_a_version(body, allowed_versions)
        if bad:
            log(f"  dropped copy for {release.short_name}: invented version {bad}")
            continue
        bodies[index] = body
    return intro, bodies


def write_principles() -> dict[str, str]:
    """Refreshed manifesto bodies. An empty dict is a perfectly good result --
    home.html then shows the copy it ships with."""
    listing = "\n\n".join(
        f"- {key} (\"{PRINCIPLE_KEYS[key]}\")\n  Subject: {PRINCIPLE_BRIEFS[key]}"
        for key in PRINCIPLE_KEYS)
    shape = json.dumps({"principles": {"free": "...", "ads": "..."}})
    prompt = (
        "Rewrite the seven manifesto principles on the Opticell home page. Each one "
        "is shown on its own when a visitor taps the card, so each must stand alone "
        "and read as a considered statement of how the company works.\n\n"
        "Each principle has its own subject. Stay on it -- seven variations on "
        "'our pricing is fair' would make the page worse, so do not let one card "
        "drift into another's territory.\n\n"
        f"{listing}\n\n"
        f"The commercial facts, which several of these depend on: {PRICING_TRUTH}\n\n"
        "Real app names you may mention: MyLLM, WorkFlow, Hanyu, DrawPad, E-Grid, "
        "LinkFindr, RunFindr, WalkFindr, Reverie, Dice Touch, My Business Portal.\n\n"
        f"Write {MIN_PRINCIPLE_CHARS}-{MAX_PRINCIPLE_CHARS} characters per principle "
        "-- aim for 280-450, which is what the card is designed to hold. Three or "
        "four sentences, no heading, no bullet points, plain prose. Make the "
        "argument for the principle; do not merely restate the title. Say 'lifetime "
        "unlock', never 'permanent license'.\n\n"
        f"Reply with exactly this JSON shape, using the keys above: {shape}"
    )

    data = call_model(prompt, "manifesto principles")
    if not data:
        return {}

    block = data.get("principles")
    if not isinstance(block, dict):
        block = data                                # some replies skip the wrapper

    out: dict[str, str] = {}
    for key, value in block.items():
        if key not in PRINCIPLE_KEYS:
            continue
        body = clean_body(value)
        if not MIN_PRINCIPLE_CHARS <= len(body) <= MAX_PRINCIPLE_CHARS:
            log(f"  dropped principle '{key}': {len(body)} chars")
            continue
        bad = breaks_pricing(body)
        if bad:
            log(f"  dropped principle '{key}': pricing claim /{bad}/")
            continue
        out[key] = body

    missing = sorted(set(PRINCIPLE_KEYS) - set(out))
    if missing:
        log(f"  keeping the page's own copy for: {', '.join(missing)}")
    return out


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #


def build_edition(today: dt.date, window_days: int, use_llm: bool,
                  do_principles: bool = True,
                  inherited: dict[str, str] | None = None) -> dict:
    """`inherited` is the previous edition's principles, carried forward when
    we are not regenerating them. Blanking them instead would drop the page
    back to its static copy, which is not what "leave the manifesto alone"
    should mean -- the last APPROVED set is the thing worth keeping."""
    log("Facts:")
    releases = fetch_releases(today, window_days)

    log("Copy:")
    if use_llm:
        intro, bodies = write_workshop(releases, today)
        if do_principles:
            principles = write_principles()
        else:
            principles = dict(inherited or {})
            log(f"  --no-principles: carrying forward {len(principles)} "
                f"approved principle(s)" if principles else
                "  --no-principles: nothing to carry forward; the page keeps its own copy")
    else:
        log("  --no-llm: templates only")
        intro = template_intro(releases, today)
        bodies = [template_item(r) for r in releases]
        principles = dict(inherited or {})

    published = dt.datetime.combine(today, dt.time(0, 0), tzinfo=dt.timezone.utc)
    return {
        "id": today.isoformat(),
        "kind": "workshop",
        "label": "from the workshop",
        "publishedAt": published.isoformat().replace("+00:00", "Z"),
        "expiresAt": (published + dt.timedelta(days=EDITION_TTL_DAYS))
                     .isoformat().replace("+00:00", "Z"),
        "dateline": today.strftime("%-d %B %Y"),
        "intro": intro,
        "items": [
            {
                "app": release.short_name,
                "version": release.version,
                "date": release.date.isoformat(),
                "url": release.url,
                "body": body,
            }
            for release, body in zip(releases, bodies)
        ],
        "principles": principles,
    }


def merge(existing: dict, edition: dict) -> dict:
    """Newest first, one edition per id, the last KEEP_EDITIONS kept."""
    editions = [e for e in existing.get("editions", [])
                if isinstance(e, dict) and e.get("id") != edition["id"]]
    editions.insert(0, edition)
    editions.sort(key=lambda e: str(e.get("id", "")), reverse=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return {
        "schema": 1,
        "generatedAt": now.replace("+00:00", "Z"),
        "editions": editions[:KEEP_EDITIONS],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--date", help="pretend it is this day, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS,
                        help=f"how far back an update counts (default {DEFAULT_WINDOW_DAYS})")
    parser.add_argument("--no-llm", action="store_true", help="templated prose only")
    parser.add_argument("--no-principles", action="store_true",
                        help="build the strip only; leave home.html's manifesto copy alone")
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args()

    today = (dt.date.fromisoformat(args.date) if args.date
             else dt.datetime.now(dt.timezone.utc).date())
    log(f"Building the {today} edition")

    existing = {}
    if args.out.exists():
        try:
            existing = json.loads(args.out.read_text())
        except json.JSONDecodeError:
            log(f"  {args.out} was not valid JSON; starting a fresh file")
    if not isinstance(existing, dict):
        existing = {}

    # The newest edition already on file supplies the principles to carry
    # forward. Its own id may be today's, on a re-run.
    prior = next((e for e in existing.get("editions", [])
                  if isinstance(e, dict) and isinstance(e.get("principles"), dict)
                  and e["principles"]), None)

    edition = build_edition(today, args.days, not args.no_llm,
                            do_principles=not args.no_principles,
                            inherited=(prior or {}).get("principles"))
    if not edition["items"] and not edition["principles"]:
        log("Nothing to publish: no recent releases and no principle copy.")
        return 1

    document = merge(existing, edition)
    rendered = json.dumps(document, indent=2, ensure_ascii=False) + "\n"

    if args.dry_run:
        print(rendered)
        log("--dry-run: nothing written")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered)
    log(f"Wrote {args.out} -- {len(edition['items'])} item(s), "
        f"{len(edition['principles'])} principle override(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
