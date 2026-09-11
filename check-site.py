#!/usr/bin/env python3
"""Structural release gate for a static site directory.

Generalised from the gate used to ship salt-and-standard.com (a bilingual
marketing site). The business-specific checks from that deployment (exact
legal-copy sentences, a fixed EN/RO page-pair list, an email-stack lane
file, hardcoded Calendly URLs) have been stripped out; what's left is the
reusable structural core:

  1. every internal `href`/`src` resolves to a real file (directory links
     resolve to that directory's index.html; `#fragment` links must find a
     matching `id=` in the resolved document)
  2. every HTML document has a non-empty <title> and
     <meta name="description"> (except a 404 page, checked separately)
  3. a 404 page (`404.html`), if present, must have noindex, and must NOT
     carry canonical/hreflang links
  4. any page with a canonical <link> gets it checked against
     `${SITE_DOMAIN}${its own path}`; any page with hreflang <link>s gets
     every hreflang target checked for reciprocity (each hreflang'd URL
     must itself resolve to a real page)
  5. `sitemap.xml`, if present: every <loc> ends in "/", resolves to a real
     page under the site root, and has no duplicates
  6. `robots.txt`, if present: has an `Allow: /` line and references
     `${SITE_DOMAIN}/sitemap.xml`
  7. zero `prefers-color-scheme` anywhere (set `ALLOW_DARK_MODE=1` to skip
     — the salt-and-standard deployment this was extracted from is
     light-only by brand decision; that's a policy choice, not a general
     rule, hence the opt-out)
  8. zero `REPLACE-AT-DEPLOY` placeholder tokens, unless `--cutover` is
     omitted AND `ALLOW_PLACEHOLDERS` is set (pre-launch sites legitimately
     ship these; `--cutover` always requires zero)
  9. `_headers` (Cloudflare Pages / Netlify header syntax), if present: has
     X-Content-Type-Options, Referrer-Policy, Permissions-Policy and
     Content-Security-Policy lines

Configuration: `SITE_DIR` env var or first positional arg (default
"site"); `SITE_DOMAIN` env var (default "https://example.com" — set it to
your real origin, e.g. `SITE_DOMAIN=https://salt-and-standard.com`).

Uses only the stdlib (html.parser), no third-party dependencies.
"""
import os
import pathlib
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
CUTOVER = "--cutover" in sys.argv[1:]

SITE = pathlib.Path(ARGS[0] if ARGS else os.environ.get("SITE_DIR", "site")).resolve()
DOMAIN = os.environ.get("SITE_DOMAIN", "https://example.com").rstrip("/")

if not SITE.is_dir():
    print(f"FAIL: site directory not found: {SITE}")
    sys.exit(1)

FOUR_OH_FOUR = "404.html"
fail = 0


def report(ok, msg):
    global fail
    print(("PASS: " if ok else "FAIL: ") + msg)
    if not ok:
        fail = 1


# ---------------------------------------------------------------- parsing --

class PageParser(HTMLParser):
    """Single-pass extraction of everything the checks below need."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = None
        self._in_title = False
        self.meta_description = None
        self.meta_robots = None
        self.canonical = None
        self.hreflang = {}          # hreflang value -> href
        self.ids = set()
        self.hrefs = []             # (href, lineno)
        self.srcs = []              # (src, lineno)

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        lineno = self.getpos()[0]

        if "id" in attrs:
            self.ids.add(attrs["id"])
        if "href" in attrs:
            self.hrefs.append((attrs["href"], lineno))
        if "src" in attrs:
            self.srcs.append((attrs["src"], lineno))

        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = attrs.get("name", "").lower()
            if name == "description":
                self.meta_description = attrs.get("content", "")
            elif name == "robots":
                self.meta_robots = attrs.get("content", "")
        elif tag == "link":
            rel = attrs.get("rel", "").lower()
            if rel == "canonical":
                self.canonical = attrs.get("href")
            elif rel == "alternate" and "hreflang" in attrs:
                self.hreflang[attrs["hreflang"]] = attrs.get("href")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data


def parse(rel_path):
    text = (SITE / rel_path).read_text(encoding="utf-8")
    p = PageParser()
    p.feed(text)
    return p


ALL_HTML = sorted(str(p.relative_to(SITE)) for p in SITE.rglob("*.html"))
PARSED = {rel: parse(rel) for rel in ALL_HTML}

print(f"Extractable structure: {len(ALL_HTML)} HTML documents under {SITE} parsed with "
      f"html.parser (an extractor, not a validator — it tolerates malformed markup "
      f"silently, so this line is not itself a correctness guarantee, just a "
      f"precondition for the checks below).")

# --------------------------------------------------------- link resolution --

def split_fragment(href):
    if "#" in href:
        path, frag = href.split("#", 1)
        return path, frag
    return href, None


def resolve_href(href, base_dir):
    """Resolve href relative to base_dir (posix, '' = site root) to a
    (resolved_rel_path, fragment_or_None) tuple, or None if the href is
    out of scope (external domain, mailto:, tel:)."""
    if href.startswith(("mailto:", "tel:")):
        return None
    if href.startswith(("http://", "https://")):
        if href.startswith(DOMAIN):
            href = href[len(DOMAIN):] or "/"
        else:
            return None  # external site — not our graph to check

    path, frag = split_fragment(href)

    if path == "":
        combined, is_dir_hint = base_dir, True
    elif path.startswith("/"):
        raw = path[1:]
        is_dir_hint = raw == "" or raw.endswith("/")
        combined = "" if raw in ("",) else posixpath.normpath(raw)
        if combined == ".":
            combined = ""
    else:
        is_dir_hint = path.endswith("/")
        joined = posixpath.normpath(posixpath.join(base_dir, path))
        combined = "" if joined == "." else joined

    fs_path = (SITE / combined) if combined else SITE
    if is_dir_hint or (fs_path.exists() and fs_path.is_dir()):
        resolved = f"{combined}/index.html" if combined else "index.html"
    else:
        resolved = combined
    return resolved, frag


link_fail = 0
link_checked = 0
for rel_path, page in PARSED.items():
    base_dir = posixpath.dirname(rel_path)
    for kind, entries in (("href", page.hrefs), ("src", page.srcs)):
        for raw, lineno in entries:
            result = resolve_href(raw, base_dir)
            if result is None:
                continue  # external / mailto / tel — out of scope
            resolved, frag = result
            link_checked += 1
            target = SITE / resolved
            if not target.is_file():
                link_fail = 1
                print(f"  FAIL: {rel_path}:{lineno}: {kind}=\"{raw}\" -> {resolved} (no such file)")
                continue
            if frag is not None:
                if resolved not in PARSED:
                    link_fail = 1
                    print(f"  FAIL: {rel_path}:{lineno}: {kind}=\"{raw}\" -> fragment #{frag} in non-HTML target {resolved}")
                elif frag not in PARSED[resolved].ids:
                    link_fail = 1
                    print(f"  FAIL: {rel_path}:{lineno}: {kind}=\"{raw}\" -> no id=\"{frag}\" found in {resolved}")

report(not link_fail, f"all {link_checked} resolvable internal href/src links check out (broken-link gate)")

# ------------------------------------------------------- title/description --

for rel_path, page in PARSED.items():
    if rel_path == FOUR_OH_FOUR:
        continue
    ok = bool(page.title) and bool(page.meta_description)
    report(ok, f"{rel_path}: has <title> and <meta name=description>"
           if ok else f"{rel_path}: missing <title> and/or <meta name=description>")

# --------------------------------------------------------------- 404 page --

nf = PARSED.get(FOUR_OH_FOUR)
if nf is not None:
    ok = True
    if not nf.meta_robots or "noindex" not in nf.meta_robots.lower():
        report(False, f"{FOUR_OH_FOUR}: missing/incorrect noindex (got {nf.meta_robots!r})"); ok = False
    if nf.canonical is not None:
        report(False, f"{FOUR_OH_FOUR}: must NOT have a canonical link (found {nf.canonical!r})"); ok = False
    if nf.hreflang:
        report(False, f"{FOUR_OH_FOUR}: must NOT have hreflang links (found {nf.hreflang!r})"); ok = False
    if ok:
        report(True, f"{FOUR_OH_FOUR}: noindex present, no canonical/hreflang (correct)")

# ---------------------------------------------------- canonical + hreflang --

for rel_path, page in PARSED.items():
    if rel_path == FOUR_OH_FOUR:
        continue
    if page.canonical is not None:
        own_path = "/" + rel_path.rsplit("index.html", 1)[0] if rel_path != "index.html" else "/"
        expected = DOMAIN + own_path
        report(page.canonical == expected,
               f"{rel_path}: canonical matches its own URL ({expected})"
               if page.canonical == expected else
               f"{rel_path}: canonical is {page.canonical!r}, expected {expected!r}")
    for lang, href in page.hreflang.items():
        result = resolve_href(href, "") if href.startswith(DOMAIN) else None
        if result is None:
            continue  # points off-domain or couldn't be resolved — not this gate's concern
        resolved, _ = result
        ok = (SITE / resolved).is_file()
        report(ok, f"{rel_path}: hreflang={lang!r} target resolves ({resolved})"
               if ok else f"{rel_path}: hreflang={lang!r} target {href!r} does not resolve")

# ----------------------------------------------------------------sitemap --

sitemap_path = SITE / "sitemap.xml"
if sitemap_path.is_file():
    tree = ET.parse(sitemap_path)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text.strip() for el in tree.getroot().findall("s:url/s:loc", ns)]
    not_trailing_slash = [u for u in locs if not u.endswith("/")]
    report(not not_trailing_slash, f"sitemap.xml: all {len(locs)} URLs end with '/' ({not_trailing_slash!r} do not)")
    unresolved = []
    for loc in locs:
        result = resolve_href(loc, "")
        if result is None or not (SITE / result[0]).is_file():
            unresolved.append(loc)
    report(not unresolved, "sitemap.xml: every URL resolves to a real page"
           if not unresolved else f"sitemap.xml: URLs that don't resolve: {unresolved!r}")
    report(len(locs) == len(set(locs)), "sitemap.xml has no duplicate URLs")

# ------------------------------------------------------- robots.txt -------

robots_path = SITE / "robots.txt"
if robots_path.is_file():
    robots_text = robots_path.read_text(encoding="utf-8")
    report("Allow: /" in robots_text, "robots.txt: has 'Allow: /'")
    report(f"Sitemap: {DOMAIN}/sitemap.xml" in robots_text, "robots.txt: references the correct sitemap URL")

# ------------------------------------------------- prefers-color-scheme ---

if not os.environ.get("ALLOW_DARK_MODE"):
    scheme_hits = []
    for path in list(SITE.rglob("*.css")) + list(SITE.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        if "prefers-color-scheme" in text:
            scheme_hits.append(str(path.relative_to(SITE)))
    report(not scheme_hits, "zero 'prefers-color-scheme' under the site (set ALLOW_DARK_MODE=1 to allow)"
           if not scheme_hits else f"'prefers-color-scheme' found in: {scheme_hits!r}")

# ------------------------------------------------------ REPLACE-AT-DEPLOY --

replace_count = sum(
    path.read_text(encoding="utf-8").count("REPLACE-AT-DEPLOY")
    for path in SITE.rglob("*.html")
)
if CUTOVER or not os.environ.get("ALLOW_PLACEHOLDERS"):
    report(replace_count == 0, f"REPLACE-AT-DEPLOY placeholder count is {replace_count}, expected 0"
           + ("" if CUTOVER else " (set ALLOW_PLACEHOLDERS=1 for a pre-launch site that still has them)"))
else:
    print(f"SKIP: REPLACE-AT-DEPLOY count is {replace_count} (ALLOW_PLACEHOLDERS set)")

# --------------------------------------------------------- placeholder <> --

TOKEN_RE = re.compile(r"‹[^›]*›")
token_hits = []
for path in SITE.rglob("*.html"):
    for m in TOKEN_RE.finditer(path.read_text(encoding="utf-8")):
        token_hits.append((str(path.relative_to(SITE)), m.group(0)))

if CUTOVER or not os.environ.get("ALLOW_PLACEHOLDERS"):
    report(not token_hits, "zero ‹…› placeholder tokens remain"
           if not token_hits else f"‹…› placeholder tokens still present: {token_hits!r}")
else:
    print(f"SKIP: {len(token_hits)} ‹…› placeholder tokens present (ALLOW_PLACEHOLDERS set)")

# --------------------------------------------------------------- _headers --

headers_path = SITE / "_headers"
if headers_path.is_file():
    headers_text = headers_path.read_text(encoding="utf-8")
    for header_name in (
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Content-Security-Policy",
    ):
        present = header_name in headers_text
        report(present, f"_headers: has a {header_name!r} line"
               if present else f"_headers: missing {header_name!r} line")

# ------------------------------------------------------------------ done --

print()
if fail:
    print("FAIL: check-site found one or more structural defects (see above)")
else:
    print("PASS: check-site — all structural checks green" + (" (--cutover)" if CUTOVER else ""))
sys.exit(fail)
