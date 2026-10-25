# Waltham Forest SEND data

A static website showing how special educational needs and disability (SEND)
services in Waltham Forest are performing, and what targets exist. Every figure
links back to a public source:

- **Department for Education statistics**, downloaded automatically from
  [Explore Education Statistics](https://explore-education-statistics.service.gov.uk/):
  EHC plan numbers, requests, 20-week timeliness, annual reviews, placements,
  SEND Tribunal appeal rates, results at key stages 2 and 4, and exclusions.
  Each figure is shown for Waltham Forest, London and England, with a ranking
  against the other London boroughs.
- **Local Government and Social Care Ombudsman**, downloaded automatically:
  every published decision about the council (SEND decisions are picked out
  by the Ombudsman's own category) and its yearly complaint statistics.
- **NHS England waiting times**: children's community health services
  waiting lists and autism assessment waits for NELFT, North East London,
  London and England. NHS England blocks automated downloads, so these are
  downloaded by hand and cut down with `scripts/extract_nhs.py`.
- **Council, NHS and Ofsted documents**: committee papers, the SEND Local Area
  Improvement Plan and its highlight reports, budget reports, and the 2025 area
  SEND inspection. These are entered by hand with page numbers.

## How it works

```
data/dfe_sources.yaml     which DfE data sets to download
scripts/fetch_dfe.py      downloads them, keeps England + London rows -> data/dfe/*.csv
scripts/fetch_lgo.py      downloads Ombudsman decisions and statistics -> data/lgo/*.csv
scripts/extract_nhs.py    cuts hand-downloaded NHS files down to NEL rows -> data/nhs/ (see data/nhs/README.md)
data/local/*.yaml         figures copied from council/NHS/Ofsted documents, with page refs
scripts/metrics.py        calculates the metrics shown on the site
scripts/build.py          renders site/templates/*.html -> _site/
```

The site is plain HTML and CSS. Charts are inline SVG, so no JavaScript
libraries or external services are needed. A small script adds hover
tooltips. Every chart has a "Show the numbers" table.

### Build locally

```sh
pip install -r requirements.txt
python scripts/build.py          # uses the committed data, no network needed
python -m http.server -d _site   # then open http://localhost:8000
```

### Refresh the DfE statistics

```sh
python scripts/fetch_dfe.py                  # everything (about 2 minutes)
python scripts/fetch_dfe.py ehcp_timeliness  # or one data set
```

Refresh the Ombudsman data the same way with `python scripts/fetch_lgo.py`.

The `Refresh DfE and Ombudsman data` workflow runs both on the 3rd of each
month and opens a pull request if anything changed. Upcoming release dates
are kept by hand in `data/local/release_calendar.yaml`.

Data sets with an `api_id` follow new DfE releases automatically. Data sets
with a `file_id` are not in the DfE API yet, so their id changes when a new
release comes out. Check them each year:

| Data set | Usually published |
|---|---|
| Education, health and care plans (annual reviews, assessments, appeal rates) | June |
| Special educational needs in England | June |
| Key stage 2 attainment | September (provisional), December (revised) |
| Suspensions and permanent exclusions | July |
| LA and school expenditure (section 251 outturn) | Usually winter |
| Pupil absence (autumn and spring terms) | Summer, with the full year in spring |
| Early years foundation stage profile | Autumn |
| Key stage 4 destination measures | Autumn |
| NEET age 16 to 17 by local authority | Summer |

To find a new `file_id`, open the release on Explore Education Statistics,
go to "Explore data", open the data set and copy the id from the data
catalogue URL (`/data-catalogue/data-set/<id>`). The tribunal appeal rate is
a supporting file, not a data set. Its `download_url` points at a specific
release and needs updating by hand too.

### Add or update a council figure

1. Add the document to `data/local/sources.yaml`, using the publisher's own
   URL (for example `democracy.walthamforest.gov.uk` or `civico.net`).
2. Add the figure to `data/local/council_reported.yaml`, with the source id
   and page number. Copy values as printed. If a label is unclear, keep it and
   explain in `note`.
3. Run `python scripts/build.py` and check the page.

## Hosting

**GitHub Pages:** in the repository settings, go to Pages and set the source
to "GitHub Actions". The `Build and deploy site` workflow publishes `_site/`
on every push to `main`. The build writes a `CNAME` file for
`wfsenddata.org.uk`. In Pages settings, set the custom domain to
`wfsenddata.org.uk` and tick "Enforce HTTPS". At your DNS provider add `A`
records for the apex domain pointing at GitHub's Pages addresses
(185.199.108.153, 185.199.109.153, 185.199.110.153, 185.199.111.153) and a
`CNAME` record for `www` pointing at `vrih.github.io`.

**Cloudflare Pages:** set the build command to
`pip install -r requirements.txt && python scripts/build.py` and the output
directory to `_site`.

## Contact

info@wfsenddata.org.uk

## Licence and attribution

DfE statistics are Crown copyright, reused under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
Council and Ofsted documents are quoted for comment and linked at source.
