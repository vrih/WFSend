# CLAUDE.md

Static site at wfsenddata.org.uk showing how SEND services in Waltham Forest
are performing. It's for parents and carers first, then councillors and
journalists. The README covers the data pipeline and refresh steps; read it
before changing anything.

## Rules that matter most

- **Every figure links to a public source.** DfE figures cite the release
  (`cite_dfe`). Every other figure cites a document in
  `data/local/sources.yaml` by id, with a page number (`cite(source, page)`).
  Add the document to `sources.yaml` before using it anywhere.
- **Copy values exactly as published.** Don't edit or round the extracted
  rows. If a label or figure is unclear, keep it and explain in `note`. Treat
  suppressed values (`x`, `c`, `z`, `u`, `low`, ...) as missing; see
  `SUPPRESSED` in `scripts/metrics.py`.
- **Use the publisher's own URL** (gov.uk, `democracy.walthamforest.gov.uk`,
  `civico.net`, `thehub-beta.walthamforest.gov.uk`, `files.ofsted.gov.uk`),
  never a third-party mirror.
- **Be fair.** Say what the data can and can't show: recording changes,
  small numbers, definitions that differ between sources. Put this in a
  chart `note` or `p.note`, as the existing pages do. Don't speculate about
  causes.

## How the code is laid out

```
data/dfe_sources.yaml   DfE data sets to download, and the statistical neighbours
scripts/fetch_*.py      download a source -> data/<source>/*.csv + manifest.json
scripts/extract_nhs.py  cuts hand-downloaded NHS files down (NHS England blocks automated downloads)
data/local/*.yaml       figures copied by hand from documents, with page refs
scripts/metrics.py      one function per metric, returning a dict built by build()
scripts/charts.py       inline SVG charts
scripts/build.py        renders site/templates/*.html -> _site/
```

Adding a new downloaded source usually means:

1. Write `scripts/fetch_<source>.py`, modelled on `fetch_lgo.py`: stdlib
   `urllib`, a `wfsend-data-fetch` User-Agent, a module docstring saying what
   it writes and how to run it. It writes small CSV extracts and a
   `manifest.json` recording where and when the data was downloaded.
2. Keep only the rows the site needs: Waltham Forest, London, England and
   the statistical neighbours (`statistical_neighbours` in
   `data/dfe_sources.yaml`). Commit the extract, never the raw download.
3. Add a metric function to `scripts/metrics.py`. Compare across
   `WF`, London, England and `SN` (similar areas), and rank against London
   boroughs and neighbours where the data allows.
4. Show it on a template using `figure()` (a global from `build.py`) and
   the macros in `_macros.html` (`tile`, `compare`, `simple_table`). Every
   chart needs a "Show the numbers" table, which `figure()` provides.
5. Add the fetch step to `.github/workflows/refresh-data.yml` if it can run
   unattended. Update the README's source list and "How it works".

Runtime dependencies are only `jinja2` and `pyyaml`. Don't add more without
a good reason; optional extras like `openpyxl` stay optional.

## Pages

- Plain HTML and CSS, charts as inline SVG, no JavaScript libraries or
  external services. JavaScript only for small enhancements (tooltips, the
  deadlines calculator), and the page must work without it.
- Must meet WCAG 2.2 AA: headings in order, `scope` on table headers, alt
  text or text equivalents for charts, sufficient contrast. Check new pages
  with axe-core (Playwright and Chromium are available in cloud sessions).
- Every `h2` and `h3` gets an id and a `#` link to itself at build time
  (`add_anchors()` in `build.py`), and a chart's heading links to its
  `<figure>` id. Give a heading an explicit `id` only when other pages link to it.
- New pages go in the nav in `base.html`, in `sitemap.xml` (built in
  `build.py`), and need a `title` and `description` block.
- Page titles lead with what the page is about and name Waltham Forest
  ("EHC plans in Waltham Forest"). Descriptions give the headline figure
  where there is one: they are reused in `llms.txt` and structured data.
- In templates, show a manifest's download date with `fetched(manifest)`, not
  `manifest.fetched`, so it counts towards the page's "Figures last updated".

## Writing style

Plain English for parents, following GOV.UK style: short sentences, active
voice, "EHC plan" not "EHCP", sentence case headings, no jargon without
explanation, numbers as digits. Say "the council", "similar areas" (not
"statistical neighbours", except where `sources.html` explains the term)
on the site.

## Checking a change

```sh
pip install -r requirements.txt
python scripts/build.py          # must run with no network access
python -m http.server -d _site   # look at the pages you changed
```

There are no unit tests. The build failing (Jinja `StrictUndefined`) is the
main check, so run it and look at the rendered page before pushing.

## Git

One issue per branch and pull request. Commit messages: a short imperative
subject, then a body saying why. Reference the issue (`Closes #n`) in the PR.
