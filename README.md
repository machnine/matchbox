# cRF and matchability calculator

## Data sources
*10,000 donors* used in the [NHSBT-ODT cRF calculator](https://www.odt.nhs.uk/transplantation/tools-policies-and-guidance/calculators/).

Matchbox records the upstream Excel filename and file-size signature supplied with this release. API results also include
the verified data-release identifier, derived donor database filename, SHA-256 fingerprint, donor table, and
matchability-band version. The fingerprint identifies the exact derived data artifact even though upstream source
versioning is opaque. Custom artifacts do not inherit the bundled release identifier automatically.

## Caclulations
### Sensitisation: 
- *cRF* = calculated Reaction Frequency
- *D<sub>i</sub>* = ABO identical and HLA-incompatible donors
- *D<sub>all</sub>* = all ABO-identical donors
	
	$`cRF = \frac{Di}{Dall} \times 100\%`$


### Donor pool:
The calculation scores against blood group identical donors by default, which is what the official calculator does.
Kidney allocation policy (POL186) offers several recipients compatible non-identical donors as well, and which ones
depends on the patient's tier. The `pool` parameter selects the denominator:

| Recipient | `identical` | `tier_b` | `tier_a` |
|-----------|------------:|---------:|---------:|
| O         | O — 4,620   | O — 4,620 | O — 4,620 |
| A         | A — 4,094   | A — 4,094 | A+O — 8,714 |
| B         | B — 962     | B+O — 5,582 | B+O — 5,582 |
| AB        | AB — 324    | AB+A — 4,418 | AB+A+O — 9,038 |

Tier is an input, not something the calculator derives: the 7-year waiting rule is patient data it never sees, and the
matchability-10 rule is circular. Note B and AB recipients are offered non-identical donors in *both* tiers, so
`identical` is the only way to reproduce the value NHSBT holds for them.

**The matchability score is not comparable over a wider pool.** It is a decile rank derived from blood group identical
counts, so a count drawn from a larger pool reads low against it - a group AB patient whose true band is 6 reads as
band 1. The response carries `matchability_status`, which is `banded` when the pool is blood group identical and
`not_comparable_wider_pool` otherwise; the same status is written to exported profiles. Re-deriving honest bands needs
every patient's accessible count at once, which a single-patient calculator cannot do.

### Allele-level HLA-DP4:
The donor cohort records HLA-DP at broad antigen level, so `DPB0401` and `DPB0402` cannot be scored against a donor
column. They are scored against the expected carriers of that allele among the DP4-positive donors, approximating the
way NHSBT handles these two specificities:

- *N* = blood group identical donors
- *S* = donors excluded by the patient's other specificities
- *D* = the further DP4 donors that only the DP4 entry excludes
- *f* = carrier fraction of the allele among DP4-positive donors

	$`cRF = \frac{S + f \times D}{N} \times 100\%`$

Selecting `DPB4`, or both alleles together, resolves the entry to the broad antigen (the *f* = 1 limit); omitting it
is the *f* = 0 limit. Only cRF is weighted - matchability counts whole donors and scores an allele entry as broad DP4.

The carrier fractions live in the `dp4_allele_frequencies` table of the donor database, so they version with the data
release. The bundled values are 0.86 (DPB1\*04:01) and 0.26 (DPB1\*04:02), from HLA-DPB1 typing of 456 UK deceased
solid organ donors.

### Matchability:
- *D<sub>fm</sub>* = the number of ABO identical, HLA-compatible and favourably matched donors 
- Assign a matchability point according to the following matchability banding:
  

| BG  | 1   | 2   | 3   | 4   | 5   | 6   | 7   | 8   | 9   | 10  |
|----|----|----|----|----|----|----|----|----|----|----|
| A   | 360 | 279 | 228 | 178 | 146 | 115 | 87  | 63  | 19  | 0   |
| B   | 70  | 54  | 42  | 35  | 29  | 24  | 19  | 14  | 6   | 0   |
| O   | 405 | 311 | 247 | 193 | 157 | 128 | 103 | 74  | 34  | 0   |
| AB | 23  | 14  | 10  | 8   | 6   | 3   |     | 2   |     | 0   |

NB: The bandings changes at each release of the [official calculator](https://www.odt.nhs.uk/transplantation/tools-policies-and-guidance/calculators/)

## How to deploy this app
### Docker image from Dockerfile
```bash
/* Building Docker Image */
docker build . -t matchbox:latest

/* Running Docker container mapping port 80 to external port 4000 */
docker run -d -p 4000:80 --restart always matchbox:latest
```
### Docker image from GitHub Packages
```bash
/* Pulling the image */
docker pull ghcr.io/machnine/matchbox:latest

/* Running Docker container mapping port 80 to external port 4000 */
docker run -d -p 4000:80 --restart always ghcr.io/machnine/matchbox:latest
```

### Deploy by docker-compose
Copy the *docker-compose.yml* file to deployment location
```bash
/* Run docker compose */
docker compose up -d
```

## API endpoint
This app has one GET endpoint */calc/* which accepts the following queries:

```bash
GET /calc/?bg=O&specs=A2,A11,B64,CW15,DR15,DQ6,DPB2&recip_hla=B7,B18,DR9,DR2&donor_set=0 HTTP/1.1
```

The calculation endpoint allows 300 requests per minute per client by default.
Set `MATCHBOX_CALC_RATE_LIMIT` to another SlowAPI limit string (for example,
`600/minute`) when running a controlled batch deployment.

- **bg**: blood group e.g. "A"
- **specs**: antibody specs e.g. "A1,B2,DR1". `DPB0401` and `DPB0402` are allele-level HLA-DP4 entries scored by
  carrier frequency rather than against a donor column - see *Allele-level HLA-DP4* below
- **donor_set**: the all-donor reference calculation [0, default], aligned with the current ODT workbook; or the DP-typed-only subset
  [1], a non-official subset analysis
- **pool**: donor blood groups scored against - `identical` (default, blood group identical), `tier_b` or `tier_a` (the
  groups allocation policy offers). The response reports `pool`, `pool_groups`, `pool_size` and `matchability_status`
- **recip_hla**: recipient HLA-B and DR type, e.g. "B7,B8,DR9". Recognised split inputs are converted to the broad
  specificities used by the calculation; the response reports both `recip_hla_used` and `recip_hla_conversions`.

The response includes `donor_set`, `donor_cohort`, `calculation_mode`, `calculated_at`, and `provenance` alongside the
existing raw result fields. Raw DP-subset matchability values remain in the API for compatibility. Saved browser profiles
and TSV exports intentionally store Matchability and Favourable as null/blank for the DP-typed subset, because the
published matchability bands apply to the full donor cohort. The appended TSV audit columns include an export schema
version; the original eight columns retain their existing order.

## Google Analytics
To use Google Analytics, add the environment variable at docker run
```bash
docker run -d -p 4000:80 -e GA_TRACKING_ID=G-YOUR_TRAKCKING_ID --restart always matchbox:latest
```

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
