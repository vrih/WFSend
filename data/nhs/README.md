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

## 2. Community health services waiting lists (monthly)

https://digital.nhs.uk/data-and-information/publications/statistical/mi-nhse-community-health-service-waiting-lists

Download the provider-level file for each month you want (CSV, XLSX or zip),
then run:

```sh
python scripts/extract_nhs.py community_waits ~/Downloads/<file>
```

XLSX files need `pip install openpyxl`. CSV and zip files need only Python.

## Then

Commit the new folders under `data/nhs/autism/` or `data/nhs/community_waits/`
and push. The script prints how many rows it kept from each file. If it says
"no matching rows found", the file is probably a national-only summary rather
than the provider or ICB breakdown.
