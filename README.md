# Site Quality Gates

> Status: implementation evidence; no live/hosted service claimed. These are
> the release-gate scripts used to ship salt-and-standard.com, extracted and
> (where noted) generalised for standalone use.

Static-site release gates: structure/placeholder assertions, WCAG contrast,
a claims allowlist, legacy-domain leakage detection, and a CSP/HSTS header
template. Used to ship salt-and-standard.com.

## Scripts

- **`check-site.py`** — structural gate over an HTML site directory: broken
  internal links, every page has a title + meta description, canonical/
  hreflang consistency, sitemap.xml/robots.txt validity, zero
  `prefers-color-scheme` by default, and detection of unfilled
  `REPLACE-AT-DEPLOY` / `‹…›` deploy placeholders. Generalised from the
  original salt-and-standard-specific version (which hardcoded an 8-page
  EN/RO sitemap, exact legal-copy sentences, and an email-stack decision
  file) into a directory-agnostic structural check.

  ```bash
  SITE_DOMAIN=https://example.com python3 check-site.py path/to/site
  ```

  Configuration: first positional arg or `SITE_DIR` env var (default
  `site`), `SITE_DOMAIN` env var (default `https://example.com`).
  `example-site/` is a 1-page fixture that exercises every check:

  ```bash
  python3 check-site.py example-site
  ```

- **`check-contrast.py`** — WCAG 2.1 SC 1.4.3 contrast gate over a
  stylesheet: parses CSS rules with a `color:` declaration, resolves
  foreground/background per an explicit surface map, and fails on any
  colour it can't classify or any pair under threshold. The palette/
  selector logic (`--ss-*` custom-property names, rail/logo/large-text
  exemption lists) is specific to the design system it was built for —
  pointing it at another site's CSS means updating those constants — but
  the file path is configurable:

  ```bash
  python3 check-contrast.py path/to/style.css   # or: CSS_PATH=... / SITE_DIR=...
  ```

- **`check-claims.sh`** — greps operational docs/HTML for prohibited or
  unreviewed marketing claims (a credential mention, an overstated job
  title, a retired phrase), failing on anything not recorded verbatim in
  `claims-allowlist.txt`. The patterns in this copy are the actual ones
  used for salt-and-standard.com; adapt the `check` calls at the bottom for
  your own claims. `CLAIMS_ROOT` (default: the script's own directory) and
  `CLAIMS_ALLOWLIST` (default: `claims-allowlist.txt`) are configurable.

- **`check-domains.sh`** — fails if a retired domain/email fragment still
  appears in docs/HTML/CSS/SVG, so a domain migration doesn't leave stale
  references behind. `LEGACY_DOMAIN` (default: the domain this gate was
  built to catch) and `CLAIMS_ROOT` are configurable.

- **`headers.example`** — a Cloudflare Pages/Netlify `_headers` file
  template: HSTS, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and a CSP with the specific directives the source
  site's Calendly embed needed. Copy it to `_headers` in your site's output
  directory and adjust the CSP for your own third-party embeds.

## Running the gates

```bash
python3 check-site.py example-site
python3 check-contrast.py path/to/style.css   # needs a real stylesheet
bash check-claims.sh
bash check-domains.sh
```

## CI

`.github/workflows/ci.yml` runs `check-site.py` against `example-site/`,
plus `check-claims.sh` and `check-domains.sh` against this repo itself, on
every push/PR.
