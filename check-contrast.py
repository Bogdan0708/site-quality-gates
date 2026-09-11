#!/usr/bin/env python3
"""WCAG contrast gate for site/style.css — static CSS analysis, not computed
styles.

What this script does: it parses every CSS rule block in style.css, and for
every rule that carries a `color:` declaration (the actual rendered text
colour a browser would apply to elements matching that selector — it does
NOT inspect the HTML, so a selector that never matches any element on the
site is still checked), it:

  1. resolves the foreground colour to one of this palette's known tokens
     (green/ink/muted/cream/brass/white) or literal-equivalent hex/rgb(a)
     value — an unresolvable value FAILS the build outright ("unregistered
     foreground colour"), since a colour we can't classify has no computed
     contrast pair and could be silently under-contrast;
  2. resolves the background it actually sits on, via an explicit surface
     map (see SURFACE below) — not a fixed list of hand-picked pairs. The
     rule is: if the SAME rule block also declares its own `background`/
     `background-color`, that wins; otherwise, if the selector is a known
     rail/top-bar selector (see RAIL_CONTEXT_SELECTORS), the surface is the
     green rail; otherwise the surface defaults to the cream ledger column,
     the only other large surface on this site. A selector with neither an
     own-background nor a rail match — including one an author just added
     and forgot to place — gets the cream default, so a light foreground
     with no dark-surface mapping fails loudly instead of skipping silently;
  3. picks the WCAG 2.1 SC 1.4.3 threshold for that selector: 4.5:1 for
     body-size text, or 3.0:1 for entries in LARGE_TEXT_ALLOWLIST (an
     explicit selector + reason list — large-scale text or purely
     decorative/non-text glyphs only; nothing gets the lower bar by
     accident) or LOGO_EXEMPT_SELECTORS (WCAG's logo/brand-name text
     exemption — reported, not gated, per SC 1.4.3's own carve-out);
  4. computes the actual contrast ratio and reports PASS/FAIL.

What this does NOT cover: it is static analysis of style.css's declared
rules, not of computed/rendered styles — it doesn't resolve cascade
specificity conflicts between multiple rules matching the same element,
doesn't know which selectors actually match real markup, and doesn't
evaluate media-query-gated overrides as a separate cascade (a rule inside
`@media` is still parsed and checked like any other, on its own declared
background, since this stylesheet doesn't vary colours or vary text-size
across breakpoints today). Backgrounds that resolve to a translucent
rgba(...) are composited against the cream surface (the only surface these
translucent brass tints are ever used against in this stylesheet) — that
is an assumption pinned here, not a general compositor. Foreground colours
expressed as a translucent rgba(...) (`.rail-foot`) are classified by their
RGB channel match only, i.e. as if fully opaque; every such usage in this
stylesheet already clears its threshold with wide margin at full opacity,
so this cannot hide a real regression today, but it is not exact rendered
alpha-blend math.

Brass (--ss-brass) on cream is the one pair in this palette that clears the
large-text/decorative bar (3.0) but not the body-text bar (4.5) — see
brand/BRAND.md's "brass is accent-only" rule. Any rule whose foreground
resolves to brass must be in LARGE_TEXT_ALLOWLIST or LOGO_EXEMPT_SELECTORS
— an unreviewed brass-as-text usage fails outright regardless of what its
numeric ratio happens to be, since brass body copy is a design-system
violation even where a particular pair might numerically scrape past 3.0.

Uses only the stdlib (re), matching the other scripts/check-*.
"""
import os
import pathlib
import re
import sys

# Configuration: first positional arg, or CSS_PATH env var, or
# ${SITE_DIR:-site}/style.css. This checker's palette/selector logic below
# (--ss-* token names, RAIL_CONTEXT_SELECTORS, LARGE_TEXT_ALLOWLIST, ...) is
# specific to the design system it was built for (salt-and-standard.com) —
# pointing it at another site's CSS will need those constants adjusted, but
# the file location itself is configurable.
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
if _args:
    CSS_PATH = pathlib.Path(_args[0])
else:
    CSS_PATH = pathlib.Path(os.environ.get(
        "CSS_PATH",
        pathlib.Path(os.environ.get("SITE_DIR", "site")) / "style.css",
    ))

if not CSS_PATH.is_file():
    print(f"FAIL: stylesheet not found: {CSS_PATH}")
    sys.exit(1)

css = CSS_PATH.read_text(encoding="utf-8")

fail = 0


def hexcolor(name):
    """Pull --ss-<name>'s hex value straight out of style.css so the check
    can't silently drift from the actual tokens in use."""
    m = re.search(rf"--ss-{name}:\s*(#[0-9a-fA-F]{{6}})", css)
    if not m:
        print(f"FAIL: could not find --ss-{name} in {CSS_PATH}")
        sys.exit(1)
    return m.group(1)


COLORS = {name: hexcolor(name) for name in ("green", "brass", "cream", "ink", "muted")}

# White isn't declared as a --ss-* token (no rule needs it yet), but it's a
# legitimate colour in this palette (e.g. reversed-out text on a dark fill),
# so it's registered here — if a `color:` declaration ever resolves to it,
# classification succeeds rather than the declaration falling through as
# "unregistered".
WHITE_HEX = "#ffffff"
COLORS_WITH_WHITE = dict(COLORS, white=WHITE_HEX)


def normalize_hex(value):
    """'#fff' / '#FFFFFF' / '#96762a' -> '#96762a' (lowercase, 6-digit)."""
    v = value.strip().lstrip("#").lower()
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    return "#" + v


TOKEN_BY_HEX = {normalize_hex(hexval): name for name, hexval in COLORS_WITH_WHITE.items()}


def srgb_to_linear(c):
    c = c / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)


def contrast_ratio(fg_hex, bg_hex):
    l1, l2 = relative_luminance(fg_hex), relative_luminance(bg_hex)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ------------------------------------------------- colour value parsing ---

VAR_RE = re.compile(r"^var\(--ss-([a-zA-Z0-9_-]+)\)$")
HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RGBA_RE = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$")
EXEMPT_KEYWORDS = {"inherit", "currentcolor", "transparent", "initial", "unset", "none"}


def classify(raw_value):
    """Classify a FOREGROUND (`color:`) value. Returns ('token', name),
    ('exempt', raw_value), or ('unregistered', raw_value) — unregistered
    values fail the build, since a foreground this script can't name has no
    computed contrast pair (translucent rgba(...) foregrounds are matched by
    their RGB channel only, ignoring alpha — see module docstring)."""
    v = raw_value.strip()

    m = VAR_RE.match(v)
    if m:
        name = m.group(1)
        return ("token", name) if name in COLORS else ("unregistered", v)

    if HEX_RE.match(v):
        name = TOKEN_BY_HEX.get(normalize_hex(v))
        return ("token", name) if name else ("unregistered", v)

    m = RGBA_RE.match(v)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        name = TOKEN_BY_HEX.get(f"#{r:02x}{g:02x}{b:02x}")
        return ("token", name) if name else ("unregistered", v)

    if v.lower() in EXEMPT_KEYWORDS:
        return ("exempt", v)

    return ("unregistered", v)


def resolve_background(raw_value, composite_over_hex):
    """Resolve a BACKGROUND (`background`/`background-color:`) value to a
    concrete hex colour, or None if it isn't a paintable colour (transparent/
    inherit/etc — callers treat None as 'this rule declares no real
    background of its own'). Unlike `classify()`, any literal hex/rgb(a) is
    accepted here (not just the five named tokens) — a background only
    needs a computable luminance, not a design-system name. A translucent
    rgba(...) is composited over `composite_over_hex` (see module docstring:
    pinned to the cream surface, the only backdrop these brass tints are
    ever used against today)."""
    v = raw_value.strip()

    m = VAR_RE.match(v)
    if m:
        return COLORS.get(m.group(1))  # None if the token name is unknown

    if HEX_RE.match(v):
        return normalize_hex(v)

    m = RGBA_RE.match(v)
    if m:
        r, g, b = (int(m.group(i)) for i in (1, 2, 3))
        alpha = float(m.group(4)) if m.group(4) is not None else 1.0
        if alpha >= 1.0:
            return f"#{r:02x}{g:02x}{b:02x}"
        cr, cg, cb = (int(composite_over_hex.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        rr = round(alpha * r + (1 - alpha) * cr)
        gg = round(alpha * g + (1 - alpha) * cg)
        bb = round(alpha * b + (1 - alpha) * cb)
        return f"#{rr:02x}{gg:02x}{bb:02x}"

    return None  # transparent / inherit / unresolvable keyword


# --------------------------------------------------------- surface map ----
# Selectors that sit on the green rail/top-bar rather than the cream ledger
# column, and DON'T declare their own `background` (the rail's fixed nav,
# language switch, footer line, and the wordmark's brass ampersand — all
# painted straight onto .rail's green, per the HTML nesting in every page's
# <header class="rail">). Any selector not listed here, and not itself
# declaring a background, defaults to the cream surface below.
RAIL_CONTEXT_SELECTORS = {
    ".nav a",
    ".lang-switch a",
    ".rail-foot",
    ".wordmark .amp",
}

# Large-scale (>=24px, or >=18.66px/14pt bold) or purely decorative/non-text
# usages, reviewed individually — these get the WCAG 3.0:1 bar instead of
# the 4.5:1 body-text bar. Adding an entry here is a deliberate, reviewed
# classification, not a default.
LARGE_TEXT_ALLOWLIST = {
    ".start-link-arrow":
        "decorative direction glyph (→), not text content — SC 1.4.11 non-text 3:1 threshold",
    ".start-link:hover .start-link-label,\n.start-link:focus-visible .start-link-label":
        "19.2px (1.2rem) + font-weight:700 on hover/focus — WCAG large-scale bold text (>=14pt bold)",
}

# WCAG 2.1 SC 1.4.3 explicitly exempts text that is part of a logo or brand
# name from any minimum contrast requirement. Reported (INFO), not gated.
LOGO_EXEMPT_SELECTORS = {
    ".wordmark .amp":
        "logotype ampersand on the green rail — WCAG 1.4.3 logo/brand-name exemption",
}

BODY_MIN = 4.5
LARGE_MIN = 3.0

# ------------------------------------------------------------- rule scan --

# Strip comments before splitting into rules — otherwise a `/* ... */`
# section-header comment sitting directly before a rule (no other rule in
# between) gets glued onto that rule's selector text by the splitter below,
# corrupting exact-string lookups against RAIL_CONTEXT_SELECTORS /
# LARGE_TEXT_ALLOWLIST / LOGO_EXEMPT_SELECTORS for whichever selector
# happens to come right after a comment.
CSS_NO_COMMENTS = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

rule_pattern = re.compile(r"([^{}]+?)\{([^{}]*)\}", re.S)
COLOR_DECL_RE = re.compile(r"(?<!-)\bcolor:\s*([^;]+);")
BG_DECL_RE = re.compile(r"\bbackground(?:-color)?:\s*([^;]+);")

brass_text_selectors = []    # selectors where the resolved foreground is brass
unregistered_hits = []       # (selector, raw_value) — foreground we can't classify
bg_unresolved_hits = []      # (selector, raw_value) — own background we can't resolve
used_token_names = set()

results = []  # (selector, fg_label, bg_label, ratio, minimum, note)

for selector_block, body in rule_pattern.findall(CSS_NO_COMMENTS):
    selector = selector_block.strip()

    color_matches = COLOR_DECL_RE.findall(body)
    if not color_matches:
        continue

    bg_matches = BG_DECL_RE.findall(body)
    own_bg_hex = None
    if bg_matches:
        resolved_bg = resolve_background(bg_matches[-1], COLORS["cream"])
        if resolved_bg is not None:
            own_bg_hex = resolved_bg
        elif bg_matches[-1].strip().lower() not in EXEMPT_KEYWORDS:
            bg_unresolved_hits.append((selector, bg_matches[-1].strip()))

    if own_bg_hex is not None:
        bg_hex, bg_label = own_bg_hex, f"declared background ({bg_matches[-1].strip()})"
    elif selector in RAIL_CONTEXT_SELECTORS:
        bg_hex, bg_label = COLORS["green"], "green rail (surface map)"
    else:
        bg_hex, bg_label = COLORS["cream"], "cream ledger column (default surface)"

    for raw_value in color_matches:
        kind, resolved = classify(raw_value)

        if kind == "exempt":
            results.append((selector, f"{raw_value.strip()} (exempt)", bg_label, None, None, "exempt keyword — no contrast pair"))
            continue

        if kind == "unregistered":
            unregistered_hits.append((selector, raw_value.strip()))
            continue

        # kind == "token"
        used_token_names.add(resolved)
        fg_hex = COLORS_WITH_WHITE[resolved]

        if resolved == "brass":
            brass_text_selectors.append(selector)

        if selector in LOGO_EXEMPT_SELECTORS:
            ratio = contrast_ratio(fg_hex, bg_hex)
            results.append((selector, resolved, bg_label, ratio, None,
                             f"WCAG 1.4.3 logo exemption — {LOGO_EXEMPT_SELECTORS[selector]}"))
            continue

        minimum = LARGE_MIN if selector in LARGE_TEXT_ALLOWLIST else BODY_MIN
        ratio = contrast_ratio(fg_hex, bg_hex)
        note = LARGE_TEXT_ALLOWLIST.get(selector, "")
        results.append((selector, resolved, bg_label, ratio, minimum, note))

print("Contrast results (WCAG 2.1 SC 1.4.3), one line per `color:` declaration in style.css:")
for selector, fg_label, bg_label, ratio, minimum, note in results:
    first_line = selector.splitlines()[0]
    if ratio is None:
        print(f"  SKIP: {first_line!r}: color: {fg_label} — {note}")
        continue
    if minimum is None:
        print(f"  INFO: {first_line!r}: {fg_label} on {bg_label} = {ratio:.2f}:1 — {note}")
        continue
    ok = ratio >= minimum
    if not ok:
        fail = 1
    status = "PASS" if ok else "FAIL"
    suffix = f" — {note}" if note else ""
    print(f"  {status}: {first_line!r}: {fg_label} on {bg_label} = {ratio:.2f}:1 (need >= {minimum}){suffix}")

print()

# ---- Guard: any rule whose own `background`/`background-color` value we
# couldn't resolve at all (not a known token, not a literal hex/rgb(a), not
# a recognised transparent/inherit-style keyword) fails outright — an
# unresolvable background has no computable contrast ratio and could hide a
# real regression.
if bg_unresolved_hits:
    fail = 1
    print("FAIL: unresolvable background value — add its colour to the known set or fix the CSS:")
    for selector, raw_value in bg_unresolved_hits:
        print(f"    {selector.splitlines()[0]!r}: background: {raw_value}")
else:
    print("PASS: every rule's own background declaration (where present) resolves to a computable colour")

# ---- Guard: every brass-as-text-colour rule must be an explicitly reviewed,
# large/decorative/logotype usage, regardless of what its numeric ratio
# happens to be.
unexpected_brass = [s for s in brass_text_selectors if s not in LARGE_TEXT_ALLOWLIST and s not in LOGO_EXEMPT_SELECTORS]
if unexpected_brass:
    fail = 1
    print("FAIL: brass used as a text colour on selector(s) not in LARGE_TEXT_ALLOWLIST/LOGO_EXEMPT_SELECTORS:")
    for s in unexpected_brass:
        print(f"    {s!r}")
    print("  Classify each as large-text (>=18.66px + bold, or >=24px), purely decorative,")
    print("  or logotype-exempt, and add it above — or fix the CSS to use --ss-green/--ss-ink")
    print("  if it's body-size text.")
else:
    print(f"PASS: all {len(brass_text_selectors)} brass-as-text rule(s) are reviewed large/decorative/logotype usages")

stale = (set(LARGE_TEXT_ALLOWLIST) | set(LOGO_EXEMPT_SELECTORS)) - set(brass_text_selectors)
if stale:
    fail = 1
    print("FAIL: allowlisted brass-text selector(s) no longer found in style.css (stale allowlist entry):")
    for s in stale:
        print(f"    {s!r}")

# ---- Guard: any `color:` declaration that didn't resolve to a known token
# (green/ink/muted/cream/brass/white) at all — a typo'd var(), a brand-new
# literal hex, or an unrecognised rgb()/keyword.
if unregistered_hits:
    fail = 1
    print("FAIL: unregistered foreground colour — add it to the known token set or fix the CSS:")
    for selector, raw_value in unregistered_hits:
        print(f"    {selector.splitlines()[0]!r}: color: {raw_value}")
else:
    print(f"PASS: every `color:` declaration in style.css resolves to a known token "
          f"({', '.join(sorted(COLORS_WITH_WHITE))})")

print()
print("PASS: all contrast pairs clear their WCAG threshold" if not fail else "FAIL: one or more contrast checks failed")
sys.exit(fail)
