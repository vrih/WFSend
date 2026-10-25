# NHS data (downloaded by hand)

NHS England Digital blocks automated downloads, so these files are fetched in a
browser and committed here. Keep the original file names, and don't edit the
files: the site reads them exactly as published so every figure can be traced
back.

## 1. Autism waiting times

Publication: Autism Statistics (quarterly)
https://digital.nhs.uk/data-and-information/publications/statistical/autism-statistics

1. Open the latest release, for example "Autism Statistics, July 2025 to June 2026".
2. In the "Resources" section, download the CSV files for:
   - the **Sub ICB** breakdown (Waltham Forest is in NHS North East London), and
   - the **Provider** breakdown (NELFT is North East London NHS Foundation Trust).
   If there is a single zip of all the CSVs, download that instead.
3. Put the files in `data/nhs/raw/autism/<release>/`, for example
   `data/nhs/raw/autism/2025-07_to_2026-06/`.

## 2. Community health services waiting lists

Publication: Community health service waiting lists (monthly)
https://digital.nhs.uk/data-and-information/publications/statistical/mi-nhse-community-health-service-waiting-lists

1. Open the latest month.
2. Download the file with **provider-level** data (it lists each NHS trust and
   each service line, including children's speech and language therapy,
   occupational therapy and community paediatrics).
3. Put it in `data/nhs/raw/community_waits/<yyyy-mm>/`, for example
   `data/nhs/raw/community_waits/2026-08/`.

## Adding the files

From GitHub: open the repository, go to the folder, choose
**Add file > Upload files**, drop the files in and commit to the working branch.
Or copy them into place locally and commit as usual.

Every release added here becomes part of the time series, so adding a new
release each quarter (autism) or month (community waits) builds up the history.
