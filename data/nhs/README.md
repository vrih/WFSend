# NHS data (downloaded by hand, extracted locally)

NHS England Digital blocks automated downloads, and its files are hundreds of
megabytes uncompressed. So the files are downloaded in a browser and cut down
on your own computer with `scripts/extract_nhs.py`. Only the small extracts are
committed. The original files are not, and `.gitignore` stops zips being added
by accident.

The extractor keeps rows for NELFT (North East London NHS Foundation Trust),
NHS North East London, London and England. Each extract folder has a
`source.json` recording the original file name, its size and SHA-256 hash, and
the date it was extracted, so every figure can be traced back to the exact
published file. Nothing in the extracted rows is edited.

## 1. Autism waiting times (quarterly)

https://digital.nhs.uk/data-and-information/publications/statistical/autism-statistics

Download the "Autism Waiting Time Statistics - Referral to Care Contact" zips
you want (for example "April 2026 to June 2026" and "April 2025 to March
2026"). Don't unzip them. Then run:

```sh
python scripts/extract_nhs.py autism ~/Downloads/<zip file 1> ~/Downloads/<zip file 2>
```

Where releases overlap, the later folder's figures win. NELFT's children's
figures fall by almost 90% between March and April 2026, which looks like a
recording change. `AUTISM_BREAK` in `scripts/metrics.py` keeps months from
April 2026 off the trend charts. Review it when NHS England explains the
change or a new release revises those months.

## 2. Community health services waiting lists (monthly)

https://digital.nhs.uk/data-and-information/publications/statistical/mi-nhse-community-health-service-waiting-lists

Download the provider-level file for each month you want (CSV, XLSX or zip),
then run:

```sh
python scripts/extract_nhs.py community_waits ~/Downloads/<file>
```

XLSX files need `pip install openpyxl`. CSV and zip files need only Python.

## 3. ADHD management information (quarterly)

https://digital.nhs.uk/data-and-information/publications/statistical/mi-adhd

From each release, download the three CSV files: national (for example
`ADHD_Aug26.csv`), region (`ADHD_Region_Aug26.csv`) and ICB
(`ADHD_ICB_Aug26.csv`). The summary Excel file isn't needed. Then run:

```sh
python scripts/extract_nhs.py adhd ~/Downloads/ADHD_Aug26.csv ~/Downloads/ADHD_Region_Aug26.csv ~/Downloads/ADHD_ICB_Aug26.csv
```

Each release covers the last 13 months. Where releases overlap, the release
with the latest month wins, so revised figures replace older ones. ICB and
region figures were first published in May 2026.

## 4. Mental Health Services Monthly Statistics (monthly)

https://digital.nhs.uk/data-and-information/publications/statistical/mental-health-services-monthly-statistics

From each "Performance" release, download the main data zip (for example
`MHSDS_Data_AugPerf_2026.zip`, about 4 MB zipped and 170 MB unzipped). Don't
unzip it. Then run:

```sh
python scripts/extract_nhs.py mhsds ~/Downloads/MHSDS_Data_AugPerf_2026.zip
```

Only the children and young people's measures the site uses are kept (see
`MHSDS_MEASURES` in the script). Each month adds one point to the CAMHS
charts.

If an extract was made with the wrong dataset name or before a rule existed,
move its folder into `data/nhs/<dataset>/` and cut it down in place with:

```sh
python scripts/extract_nhs.py trim mhsds
```

The script stops if the dataset name isn't one it knows, so a typo can't
create a folder the site never reads.

NELFT's children's figures change sharply in April 2026, in both this data
and the autism data. `MHSDS_NELFT_BREAK` in `scripts/metrics.py` keeps
NELFT's months from then off the CAMHS charts.

## Then

Commit the new folders under `data/nhs/` and push. The script prints how many rows it kept from each file. If it says
"no matching rows found", the file is probably a national-only summary rather
than the provider or ICB breakdown.
