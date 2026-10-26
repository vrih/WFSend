# Waltham Forest SEND data

A static website showing how special educational needs and disability (SEND)
services in Waltham Forest are performing, and what targets exist. Every figure
links back to a public source:

- **Department for Education statistics**, downloaded automatically from
  [Explore Education Statistics](https://explore-education-statistics.service.gov.uk/):
  EHC plan numbers, requests, 20-week timeliness, annual reviews, placements,
  SEND Tribunal appeal rates, results at key stages 2 and 4,
  pupils' main type of need, pupils with SEND in each mainstream school, exclusions, special school places and forecast
  demand, elective home education and children missing education. Each figure is shown for Waltham
  Forest, London, England and the average of Waltham Forest's 10 statistical
  neighbours ("similar areas"), with rankings against the London boroughs and
  against the neighbours.
- **Local Government and Social Care Ombudsman**, downloaded automatically:
  every published decision about the council (SEND decisions are picked out
  by the Ombudsman's own category) and its yearly complaint statistics.
- **Get Information About Schools**, downloaded automatically: the DfE's
  register of schools, for Waltham Forest's special schools, resourced
  provision and SEN units, with the ages and types of need each one takes.
- **ONS population estimates**, downloaded automatically from
  [Nomis](https://www.nomisweb.co.uk/datasets/pestsyoala): the number of
  children aged 2 to 18 in each area, used to show requests for an assessment per
  1,000 children so areas of different sizes can be compared.
- **Council spending over £500**, downloaded automatically from the council's
  monthly transparency reports: payments coded to its SEND services, by
  service and supplier.
- **Contracts Finder and Find a Tender**, downloaded automatically: the
  council's procurement notices, with SEND contracts awarded and planned.
- **NHS England waiting times**: children's community health services
  waiting lists, autism and ADHD assessment waits, and waits for children's
  mental health services, for NELFT, North East London, London and England. NHS England blocks automated downloads, so these are
  downloaded by hand and cut down with `scripts/extract_nhs.py`.
- **Council, NHS and Ofsted documents**: committee papers, the SEND Local Area
  Improvement Plan and its highlight reports, budget reports, and the 2025 area
  SEND inspection. These are entered by hand with page numbers.

## How it works

```
data/dfe_sources.yaml     which DfE data sets to download
scripts/fetch_dfe.py      downloads them, keeps England, London and neighbour rows -> data/dfe/*.csv
scripts/fetch_lgo.py      downloads Ombudsman decisions and statistics -> data/lgo/*.csv
scripts/fetch_gias.py     downloads the GIAS register, keeps Waltham Forest's specialist settings -> data/gias/
scripts/fetch_ons.py      downloads ONS population estimates (ages 2 to 18) -> data/ons/population.csv
scripts/fetch_spend.py    downloads the council's spending over £500 reports, keeps SEND payments -> data/spend/
scripts/fetch_contracts.py downloads the council's notices from Contracts Finder and Find a Tender -> data/contracts/
scripts/extract_nhs.py    cuts hand-downloaded NHS files down to NEL rows -> data/nhs/ (see data/nhs/README.md)
data/local/*.yaml         figures copied from council/NHS/Ofsted documents, with page refs
scripts/metrics.py        calculates the metrics shown on the site
scripts/build.py          renders site/templates/*.html -> _site/
scripts/make_icons.py     draws the favicon and home screen icons -> site/icons/ (needs Pillow)
```

Three plain-language pages answer the questions families ask when they start
out: how long an EHC plan, an autism assessment and an ADHD assessment take.
Their short answers are written in `wait_answers()` in `scripts/build.py` from
the latest figures, and reused for the page description, FAQ structured data
and `llms.txt`, so they update with each data refresh. Check the wording still
makes sense after a refresh, especially if a figure moves a lot.

The site is plain HTML and CSS. Charts are inline SVG, so no JavaScript
libraries or external services are needed. A small script adds hover
tooltips. Every chart has a "Show the numbers" table. The Deadlines page
(`site/static/deadlines.js`) works out statutory deadlines in the browser.

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

Refresh the Ombudsman data the same way with `python scripts/fetch_lgo.py`,
the list of specialist settings with `python scripts/fetch_gias.py`, and the
ONS population estimates with `python scripts/fetch_ons.py`, and the council's
spending over £500 with `python scripts/fetch_spend.py`. The GIAS file is
about 65 MB, but only Waltham Forest's specialist settings are kept. The ONS
publishes new mid-year estimates each summer.

The spending reports only use the council's current finance codes from
September 2023, so earlier payments aren't kept. From April 2026 the reports
list far fewer payments for every service. `SPEND_LAST_COMPLETE` in
`scripts/metrics.py` keeps 2026/27 off the site. Review it when the council
explains the change or republishes those months, and check `SEND_SERVICES` in
`scripts/fetch_spend.py` if the council restructures its services.

Contract notices come from `python scripts/fetch_contracts.py`. Find a Tender
has no search API, so the script reads its national feed from where the last
run stopped (`fts_read_to` in `data/contracts/manifest.json`) and keeps the
council's notices. Which notices count as SEND is decided by `SEND_NOTICE` in
`scripts/metrics.py`. Check new matches after a refresh.

The `Refresh DfE and Ombudsman data` workflow runs all six on the 3rd of each
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
| School capacity (special school places, specialist places in mainstream schools, forecasts) | Spring |

The statistical neighbours are listed in `data/dfe_sources.yaml` under
`statistical_neighbours`, copied from the DfE's Children's services
statistical neighbour benchmarking tool (on the
[LAIT page](https://www.gov.uk/government/publications/local-authority-interactive-tool-lait)).
If the DfE rebuilds the model, update the list and re-run `fetch_dfe.py` so
the extracts include any new neighbour outside London.

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
