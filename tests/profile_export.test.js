const test = require("node:test");
const assert = require("node:assert/strict");

const {
  PROFILE_HEADERS,
  buildProfileRecord,
  escapeTsvCell,
  profilesToTsv,
} = require("../static/profile-export.js");

const responseFixture = () => ({
  bg: "O",
  specs: ["A1", "DPB4"],
  results: {
    crf: 0.25,
    matchability: 9,
    favourable: 50,
    available: 327,
  },
  total: 3642,
  donor_set: 1,
  donor_cohort: "dp_typed_only",
  calculation_mode: "dp_typed_subset",
  calculated_at: "2026-07-31T12:00:00+00:00",
  recip_hla: "B44,DR17",
  recip_hla_used: ["B12", "DR3"],
  recip_hla_conversions: { B44: "B12", DR17: "DR3" },
  provenance: {
    upstream_source_file: "hla-mm-and-crf_2024.xlsb",
    upstream_source_file_size_signature: 24099579,
    donor_database: "donors.db",
    donor_database_sha256: "a".repeat(64),
    donor_table: "donors_v3",
    matchability_band_version: 4,
    data_release: "nhsbt_hla_mm_crf_2024",
  },
});

test("DP-typed profiles null matchability without mutating the raw response", () => {
  const response = responseFixture();
  const original = structuredClone(response);

  const profile = buildProfileRecord(response);

  assert.equal(profile.matchability, null);
  assert.equal(profile.favourable, null);
  assert.equal(profile.crf, 25);
  assert.equal(profile.available, 327);
  assert.equal(profile.matchability_status, "not_applicable_dp_typed_subset");
  assert.deepEqual(response, original);
  assert.equal(response.results.matchability, 9);
  assert.equal(response.results.favourable, 50);
});

test("all-donor profiles retain legitimate numeric zero values", () => {
  const response = responseFixture();
  response.donor_set = 0;
  response.donor_cohort = "all_donors";
  response.calculation_mode = "all_donors_reference";
  response.results = { crf: 0, matchability: 0, favourable: 0, available: 0 };

  const profile = buildProfileRecord(response);
  const tsv = profilesToTsv([profile]);
  const [headerLine, valueLine] = tsv.split("\n");
  const row = Object.fromEntries(
    headerLine.split("\t").map((header, index) => [header, valueLine.split("\t")[index]])
  );

  assert.equal(row["CRF (%)"], "0");
  assert.equal(row.Matchability, "0");
  assert.equal(row.Favourable, "0");
  assert.equal(row.Available, "0");
});

test("TSV keeps legacy columns first and appends authoritative context", () => {
  const profile = buildProfileRecord(responseFixture());
  const [headerLine, valueLine] = profilesToTsv([profile]).split("\n");
  const headers = headerLine.split("\t");
  const values = valueLine.split("\t");
  const row = Object.fromEntries(headers.map((header, index) => [header, values[index]]));

  assert.deepEqual(PROFILE_HEADERS.slice(0, 8), [
    "CRF (%)",
    "Matchability",
    "Favourable",
    "Available",
    "Recipient HLA",
    "Unacceptable Specs",
    "Removed",
    "Added",
  ]);
  assert.equal(row.Matchability, "");
  assert.equal(row.Favourable, "");
  assert.equal(row["Donor Set"], "1");
  assert.equal(row["Calculation Mode"], "dp_typed_subset");
  assert.equal(row["Calculation Cohort Size"], "3642");
  assert.equal(row["Recipient HLA"], "B44,DR17");
  assert.equal(row["Recipient HLA Used"], "B12,DR3");
  assert.equal(row["Donor Database SHA-256"], "a".repeat(64));
  assert.equal(row["Data Release"], "nhsbt_hla_mm_crf_2024");
  assert.equal(row["Export Schema Version"], "2");
});

test("profile antibody deltas retain the existing adjacent-profile behavior", () => {
  const previous = buildProfileRecord(responseFixture());
  const response = responseFixture();
  response.specs = ["DPB4", "B7"];

  const profile = buildProfileRecord(response, previous);

  assert.deepEqual(profile.removed, ["A1"]);
  assert.deepEqual(profile.added, ["B7"]);
});

test("TSV escaping preserves structure and neutralises spreadsheet formulas", () => {
  assert.equal(escapeTsvCell('value\twith\n"structure"'), '"value\twith\n""structure"""');
  assert.equal(escapeTsvCell('=HYPERLINK("https://example.test")'), '"\'=HYPERLINK(""https://example.test"")"');
  assert.equal(escapeTsvCell(' \t=HYPERLINK("https://example.test")'), '"\' \t=HYPERLINK(""https://example.test"")"');
  assert.equal(escapeTsvCell(-1), "-1");
});

test("profile construction fails closed for an unknown donor set", () => {
  const response = responseFixture();
  delete response.donor_set;

  assert.throws(() => buildProfileRecord(response), /invalid donor_set/);
});
