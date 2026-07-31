const MatchboxProfileExport = (() => {
  const DP_TYPED_DONOR_SET = 1;
  const PROFILE_EXPORT_SCHEMA_VERSION = 2;
  const PROFILE_HEADERS = Object.freeze([
    "CRF (%)",
    "Matchability",
    "Favourable",
    "Available",
    "Recipient HLA",
    "Unacceptable Specs",
    "Removed",
    "Added",
    "Calculated At (UTC)",
    "Blood Group",
    "Donor Set",
    "Donor Cohort",
    "Calculation Mode",
    "Calculation Cohort Size",
    "Matchability Status",
    "Recipient HLA Used",
    "Recipient HLA Conversions",
    "Upstream Source File",
    "Upstream Source Size Signature",
    "Donor Database",
    "Donor Database SHA-256",
    "Donor Table",
    "Matchability Band Version",
    "Data Release",
    "Export Schema Version",
  ]);

  const copyArray = (value) => (Array.isArray(value) ? [...value] : []);

  const buildProfileRecord = (data, previousProfile = null) => {
    if (!data?.results) {
      throw new TypeError("A completed calculator response is required");
    }
    if (data.donor_set !== 0 && data.donor_set !== 1) {
      throw new TypeError("Calculator response has an invalid donor_set");
    }

    const specs = copyArray(data.specs);
    const previousSpecs = copyArray(previousProfile?.specs);
    const isDpTypedSubset = data.donor_set === DP_TYPED_DONOR_SET;
    const hasMatchability = data.results.matchability != null && data.results.favourable != null;

    return {
      crf: data.results.crf == null ? null : data.results.crf * 100,
      matchability: isDpTypedSubset ? null : data.results.matchability,
      favourable: isDpTypedSubset ? null : data.results.favourable,
      available: data.results.available,
      recip_hla: data.recip_hla ?? "",
      specs,
      removed: previousProfile ? previousSpecs.filter((spec) => !specs.includes(spec)) : [],
      added: previousProfile ? specs.filter((spec) => !previousSpecs.includes(spec)) : [],
      calculated_at: data.calculated_at ?? null,
      bg: data.bg ?? null,
      donor_set: data.donor_set,
      donor_cohort: data.donor_cohort ?? null,
      calculation_mode: data.calculation_mode ?? null,
      cohort_size: data.total,
      matchability_status: isDpTypedSubset
        ? "not_applicable_dp_typed_subset"
        : hasMatchability
          ? "calculated"
          : "not_calculated",
      recip_hla_used: copyArray(data.recip_hla_used),
      recip_hla_conversions: { ...(data.recip_hla_conversions ?? {}) },
      provenance: { ...(data.provenance ?? {}) },
      export_schema_version: PROFILE_EXPORT_SCHEMA_VERSION,
    };
  };

  const listForTsv = (value) => (Array.isArray(value) && value.length > 0 ? value.join(",") : "");
  const mappingForTsv = (value) => (value && Object.keys(value).length > 0 ? JSON.stringify(value) : "");

  const profileToTsvRow = (row) => ({
    "CRF (%)": row.crf ?? "",
    "Matchability": row.matchability ?? "",
    "Favourable": row.favourable ?? "",
    "Available": row.available ?? "",
    "Recipient HLA": row.recip_hla || "",
    "Unacceptable Specs": listForTsv(row.specs),
    "Removed": listForTsv(row.removed),
    "Added": listForTsv(row.added),
    "Calculated At (UTC)": row.calculated_at ?? "",
    "Blood Group": row.bg ?? "",
    "Donor Set": row.donor_set ?? "",
    "Donor Cohort": row.donor_cohort ?? "",
    "Calculation Mode": row.calculation_mode ?? "",
    "Calculation Cohort Size": row.cohort_size ?? "",
    "Matchability Status": row.matchability_status ?? "",
    "Recipient HLA Used": listForTsv(row.recip_hla_used),
    "Recipient HLA Conversions": mappingForTsv(row.recip_hla_conversions),
    "Upstream Source File": row.provenance?.upstream_source_file ?? "",
    "Upstream Source Size Signature": row.provenance?.upstream_source_file_size_signature ?? "",
    "Donor Database": row.provenance?.donor_database ?? "",
    "Donor Database SHA-256": row.provenance?.donor_database_sha256 ?? "",
    "Donor Table": row.provenance?.donor_table ?? "",
    "Matchability Band Version": row.provenance?.matchability_band_version ?? "",
    "Data Release": row.provenance?.data_release ?? "",
    "Export Schema Version": row.export_schema_version ?? PROFILE_EXPORT_SCHEMA_VERSION,
  });

  const escapeTsvCell = (value) => {
    if (value == null) return "";

    let text = String(value);
    if (typeof value === "string" && /^[\s\u0000-\u001f]*[=+\-@]/.test(text)) {
      text = `'${text}`;
    }
    if (/[\t\r\n"]/.test(text)) {
      return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  };

  const profilesToTsv = (profiles) => {
    const rows = profiles.map(profileToTsvRow);
    return [
      PROFILE_HEADERS.map(escapeTsvCell).join("\t"),
      ...rows.map((row) => PROFILE_HEADERS.map((header) => escapeTsvCell(row[header])).join("\t")),
    ].join("\n");
  };

  return Object.freeze({
    PROFILE_HEADERS,
    buildProfileRecord,
    escapeTsvCell,
    profileToTsvRow,
    profilesToTsv,
  });
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = MatchboxProfileExport;
}
