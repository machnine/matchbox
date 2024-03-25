# cRF and matchability calculator

## Data sources
*10,000 donors* used int the [NHSBT-ODT cRF calculator](https://www.odt.nhs.uk/transplantation/tools-policies-and-guidance/calculators/)

## Caclulations
### Sensitisation: 
- *cRF* = calculated Reaction Frequency
- *D<sub>i</sub>* = ABO identical and HLA-incompatible donors
- *D<sub>all</sub>* = all ABO-identical donors
	
	$`cRF = \frac{Di}{Dall} \times 100\%`$


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
### Docker image from Docker Hub
```bash
/* Pulling the image */
docker pull machnine/matchbox:latest

/* Running Docker container mapping port 80 to external port 4000 */
docker run -d -p 4000:80 --restart always machnine/matchbox:latest
```

## API endpoint
This app has one GET endpoint */calc/* which accepts the following queries:

```bash
    GET /calc/?bg=O&specs=A2,A11,B64,CW15,DR15,DQ6,DPB2&recip_hla=B7,B18,DR9,DR2&donor_set=0 HTTP/1.1
```

- **bg**: blood group e.g. "A"
- **specs**: antibody specs e.g. "A1,B2,DR1"
- **donor_set**: all donors [0, default] or only donors with HLA-DPB1 types [1]
- **recip_hla**: recipient HLA-B and DR type (broad) e.g. "B7,B8,DR9"