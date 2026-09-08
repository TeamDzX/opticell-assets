#!/usr/bin/env python3
"""Checks the parts of build_content.py that cannot be exercised without the
server: reasoning stripping, JSON recovery, and the two content guards."""
import sys, importlib.util
spec = importlib.util.spec_from_file_location(
    "bc", "/Users/alex/Desktop/Opticell/assets/tools/build_content.py")
bc = importlib.util.module_from_spec(spec)
sys.modules["bc"] = bc          # dataclasses resolves annotations via sys.modules
spec.loader.exec_module(bc)

fails = []
def ok(label, got, want):
    if got != want:
        fails.append(f"{label}\n    got:  {got!r}\n    want: {want!r}")

# --- the documented jarvis quirk: CoT with an ORPHAN closing tag ------------
orphan = ('Okay, the user wants copy. I should mention {braces} and "quotes" '
          'to be tricky. </think>\n\n{"intro": "Real copy.", "items": []}')
ok("orphan </think>", bc.parse_json_reply(orphan),
   {"intro": "Real copy.", "items": []})

# --- a well-formed think block ---------------------------------------------
paired = '<think>Reasoning with { and } inside.</think>{"intro": "Hi", "items": []}'
ok("paired <think>", bc.parse_json_reply(paired), {"intro": "Hi", "items": []})

# --- a code fence, which these models emit constantly -----------------------
fenced = '```json\n{"intro": "Fenced", "items": []}\n```'
ok("code fence", bc.parse_json_reply(fenced), {"intro": "Fenced", "items": []})

# --- fence AND reasoning together ------------------------------------------
both = '<think>hmm</think>\nHere you go:\n```json\n{"intro": "Both"}\n```'
ok("fence + think", bc.parse_json_reply(both), {"intro": "Both"})

# --- prose with no JSON at all must be rejected, not guessed at -------------
ok("no json", bc.parse_json_reply("I could not do that."), None)

# --- the pricing guard: these are the claims that must never ship -----------
must_reject = [
    "Our apps are completely free with no subscriptions.",
    "No in-app purchases, ever.",
    "Free forever, and always will be.",
    "Every app is subscription-free.",
    "Pay once. One-time purchase only.",
    "Opticell apps are open-source and free.",
]
for claim in must_reject:
    if bc.breaks_pricing(claim) is None:
        fails.append(f"pricing guard MISSED: {claim!r}")

# --- and the true statement must survive it --------------------------------
must_keep = [
    "Every app is free to download, with an ultra-affordable subscription or a "
    "one-time lifetime unlock.",
    "There are no ads and no data collection.",
    "Subscribe for less, or own it for life.",
]
for claim in must_keep:
    hit = bc.breaks_pricing(claim)
    if hit is not None:
        fails.append(f"pricing guard FALSE POSITIVE on {claim!r} via /{hit}/")

# --- the free-tier guard -----------------------------------------------------
# The subtler pricing error, and the one that got through the first live run:
# not "there is no subscription" but "the free download gives you everything".
for claim in [
    "You can explore the full functionality of our software without any upfront cost.",
    "Try all the features free.",
    "Get everything at no charge.",
    "Use the full version without paying.",
]:
    if bc.breaks_pricing(claim) is None:
        fails.append(f"free-tier guard MISSED: {claim!r}")

# These are TRUE and must survive -- a false positive here quietly guts the
# manifesto, which is worse than letting one weak sentence through.
for claim in [
    "Every Opticell app is free to download from the App Store and Google Play.",
    "Free to download, then subscribe to unlock everything.",
    "An ultra-affordable subscription unlocks the full app, or buy once with a lifetime unlock.",
    "Install it free, and unlock the full experience whenever you are ready.",
    "The download is free; a one-time lifetime purchase gives you all the features for good.",
]:
    hit = bc.breaks_pricing(claim)
    if hit is not None:
        fails.append(f"free-tier guard FALSE POSITIVE on {claim!r} via {hit}")

# --- the version guard ------------------------------------------------------
allowed = {"4.3.1", "4.3", "2.2"}
ok("invented version", bc.invents_a_version("WorkFlow 9.9.9 adds tags.", allowed), "9.9.9")
ok("real version", bc.invents_a_version("WorkFlow 4.3.1 adds tags.", allowed), None)
ok("no version", bc.invents_a_version("WorkFlow adds tags.", allowed), None)

# --- body cleanup -----------------------------------------------------------
ok("strips bullet", bc.clean_body("- • A line."), "A line.")
ok("strips quotes", bc.clean_body('"A quoted line."'), "A quoted line.")
ok("collapses ws", bc.clean_body("A   line\n\nbroken."), "A line broken.")

# --- short_name -------------------------------------------------------------
mk = lambda n: bc.Release(name=n, version="1.0", date=bc.dt.date(2026, 1, 1), url="")
ok("dash listing", mk("MyLLM - Local AI Agent").short_name, "MyLLM")
ok("colon listing", mk("Hanyu: Learn Chinese Mandarin").short_name, "Hanyu")
ok("hyphen kept", mk("E-Grid").short_name, "E-Grid")
ok("plain", mk("DrawPad").short_name, "DrawPad")

if fails:
    print(f"FAIL ({len(fails)})")
    for f in fails: print(" -", f)
    sys.exit(1)
print("All guard/parse checks passed.")
