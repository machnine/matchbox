# Offer assessment tool — handoff specification

Working document for implementation. Written to be read cold by an agent with no
prior conversation context.

---

## 1. What this tool is

At the point of a deceased donor offer, a patient being considered for
antibody-incompatible transplantation has a known DSA profile against the offered
donor. The clinical question is not *is this donor compatible* — by definition it
is not — but:

> Is this incompatibility as easy as this patient is realistically going to see,
> or is it ordinary?

That question drives whether to commit to desensitisation for this offer or
decline and wait. cRF cannot answer it: cRF is a scalar describing the patient,
not a comparison between donors.

The tool answers it by ranking every donor in a reference cohort by antibody
burden against this patient, then placing the offered donor on that distribution.

**Everything is read off the cohort as it stands. Nothing is predicted.**

### What this tool is not

| Not this | Why |
|---|---|
| A time-to-offer predictor | The cohorts carry no time element and are not consecutive donors. Donation-rate extrapolation would be a rate assumption wearing the cohort's data as costume. Explicitly rejected. |
| A ranking of compatible donors | Every burden metric is zero for DSA-negative donors. They are unranked, not ranked last. Different problem, different tool. |
| An eplet-level tool | Deferred to a possible future expansion. Broad/split antigen resolution only. |
| A donor quality assessment | Age, organ quality, and cause of death are independent of HLA and are the clinician's separate axis. |
| A replacement for cRF | cRF and matchability are reported as context, not as rankings. |

---

## 2. Core computation

### 2.1 Reference population

Given a patient profile and an organ:

1. Filter the cohort to donors this patient could actually be **offered** under
   allocation policy — see §4 on ABO, which is *not* blood-group-identical.
2. Split into compatible (no DSA) and incompatible (≥1 DSA).
3. **The incompatible set is the reference population.** The offer is ranked
   within it.

Note the inversion from a cRF calculation: for a cRF 99% patient the reference
set here is ~99% of the eligible cohort, not 1%. Sparsity is not the binding
constraint it would be for compatible-donor work.

### 2.2 Burden metrics

For each donor in the reference set, over the DSA present against that donor:

| Metric | Definition | Rationale |
|---|---|---|
| Cumulative | sum of MFI across DSA | What clinicians actually use to judge burden |
| Max | highest single-specificity MFI | Distinguishes one strong DSA from several moderate |
| Mean | cumulative ÷ DSA count | Typical strength per specificity |
| Median | median MFI across DSA present | As above, robust to one outlier |

Computed twice: once on **current** MFI, once on **peak** MFI.

`mean` and `median` divide over specificities *present*, never over all
specificities in the profile. This is an easy bug to introduce with a one-hot
matrix — see §6.1.

**No metric is asserted to be correct.** There is no settled measure of
desensitisation difficulty. All are exposed; the user decides. Where they
disagree, that disagreement is itself the clinical signal (e.g. low cumulative
but high max = one dominant antibody).

### 2.3 Placement

For the offered donor, per metric, per MFI basis:

- the donor's own value
- its percentile within the reference set
- **count of donors with lower burden** — this matters more than the percentile,
  because it survives translation into a clinical conversation and because the
  percentile is nearly invariant to the ABO rule while the count is not
- count of donors sharing this donor's exact DSA specificity set

### 2.4 Mismatch level

Computed against the same reference set using the existing matchability
machinery (B/DR broad matching vs recipient, with rare-antigen defaults).

Mismatch level is a *different kind of quantity* from burden — it relates to
long-term outcome and allocation, not to how hard the incompatibility is to
strip now. They can point opposite ways. A donor low on both is the genuinely
rare offer. Present as a joint view, not a fifth parallel distribution.

---

## 3. Data

Three cohorts of 10,000 donors each.

| Set | DP typing | Role |
|---|---|---|
| Set 1 | none | Verification only, not live |
| Set 2 | none | Verification only, not live |
| Set 3 | partial — 3.6k of 10k | **Primary / live** |

Established: the three sets agree on the non-DP pathway.

### 3.1 The DP debt

This is the central data constraint and it must be visible in the product, not
buried.

- A patient **with DP antibodies** can only be assessed against Set 3's
  DP-typed subset — roughly 3,571 donors, not 10,000.
- That assessment **cannot be corroborated** by Sets 1 or 2. State this as a
  limitation rather than letting the validation design imply otherwise.
- A patient **without DP antibodies** is assessed against a full 10,000 in all
  three sets.

**Untyped ≠ negative.** In the one-hot donor matrix a donor with no DP typing has
`0` in every DPB column, which reads as "no DP DSA". This artificially places
untyped donors at the *low burden* end of the distribution — exactly the end a
clinician is inspecting. These must be masked (NaN, not 0) and the untyped count
reported alongside every result. **Fix this before anything else is built on
top of it.**

### 3.2 Representativeness check (do this early)

The 3.6k DP-typed subset was almost certainly not sampled at random. Before
relying on it, compare it against the remaining 6.4k on everything they share —
A/B/C/DR/DQ allele and haplotype frequencies, ABO distribution. If
indistinguishable, representativeness is defensible with evidence. If not,
that is a finding in its own right.

Do **not** impute DP from DR/DQ linkage. It would restore the appearance of 10k
while producing rankings that are partly a haplotype model's output rather than
observed donors.

### 3.3 Verification vs replication

Keep these separate in code and in the write-up:

- **Verification** — does the code compute what it claims? Synthetic cases with
  hand-checkable answers: no antibodies, an unacceptable covering a common
  antigen, donor identical to patient, single DSA, all-DSA.
- **Replication** — is a donor's position a property of the patient or an
  artefact of cohort choice? Run defined profile–donor pairs through all three
  sets and compare the *positional* statement. A donor top-decile in one cohort
  and mid-pack in another is a real problem.

---

## 4. Allocation policy

### 4.1 ABO — not identical-only

The existing cRF calculator filters to blood-group-identical donors. NKOS
(POL186 Table A) offers several recipients compatible non-identical donors, so
identical-only understates the pool.

| Recipient | Identical only | Offerable, tier A | Offerable, tier B |
|---|---|---|---|
| O | 4,620 | 4,620 | 4,620 |
| A | 4,094 | 8,714 | 4,094 |
| B | 962 | 5,582 | 5,582 |
| AB | 324 | 9,038 | 4,418 |

For cRF this barely moves the percentage, because ABO and HLA are roughly
independent. **Here it is worse**, because the reported counts scale directly
with the denominator: an AB recipient in tier A has 9,038 offerable donors
against 324 identical. "3 donors carry a lower burden" versus "84 donors carry a
lower burden" are two entirely different clinical situations.

Implement the eligibility mapping as a **lookup keyed on organ and tier**, not
as logic embedded in the query. Pancreas allocation differs from kidney, and a
further scheme should be configuration rather than a rewrite.

Worth testing empirically: compare the burden distribution across ABO strata for
a given patient. Independence is assumed, not established, and both ABO and HLA
frequencies vary with ancestry.

### 4.2 Tier

Derived, with override. Tier A if any of:

- cRF 100%
- matchability 10
- waiting time > 7 years (kidney)

The first two are computed from the profile. Waiting time is an input. In
practice the wait-time route rarely operates alone — patients waiting that long
are usually already cRF 100 or matchability 10 — so do not build boundary-
crossing features around it.

Note that cRF 100 here means *no compatible donors in this cohort*, which is a
resolution limit rather than a biological statement, and depends on both the DP
toggle and the ABO denominator. Tier derivation therefore inherits both choices.

---

## 5. API

### 5.1 Inputs

| Field | Notes |
|---|---|
| Specificities + MFI | Per specificity: current MFI, peak MFI. Peak optional — if absent, run current-only and mark peak unavailable. |
| Patient HLA type | Broad/split. Needed for mismatch level; burden metrics do not require it. |
| Donor HLA type | Broad/split, same vocabulary as the cohort. |
| Patient blood group | |
| Donor blood group | Determines whether the offer is identical or compatible-non-identical; the reference set must match the offer's actual relationship. |
| Organ | Selects the allocation policy bundle. |
| Waiting time | For tier derivation. |
| cRF | Optional. If supplied and it differs from the computed value, return both and flag — never silently accept. |
| DP mode | Three-state: include / exclude / auto. Not boolean. |
| Tier | Optional override. Response states whether derived or supplied. |

Antigen vocabulary is fixed at broad/split, matching the donor database exactly.
Reuse the existing calculator's vocabulary and validation. Conversion from
allele-level is the caller's responsibility and explicitly out of scope.

Document the broad/split matching rule precisely — whether a patient antibody
entered as a broad implies its splits in the donor cohort, and the reverse.
Callers will differ from each other here without noticing.

### 5.2 Shape

Two calls, not one:

1. **Profile → distributions.** Returns the reference set and the four
   distributions (×2 MFI bases). Cacheable per profile; a lab assessing one
   patient over a week pays for it once, and a UI can mark several offers on one
   backdrop.
2. **Donor → placement.** Returns values, percentiles, and counts against a
   previously computed distribution.

### 5.3 Response must be self-describing

Every response carries: cohort set, DP mode used and resulting cohort size,
ABO rule and tier applied, policy configuration version, antigen vocabulary
version, and DSA threshold. A stored result should be interpretable years later,
and two runs that used different toggles must not look comparable when they
are not.

Where a choice was made by default rather than explicitly, say so, and flag when
the alternative would have differed materially.

---

## 6. Implementation notes

### 6.1 Reuse the one-hot matrix

The existing calculator stores donor types as a one-hot DataFrame, which makes
every metric a matrix operation rather than a per-donor loop:

```python
mfi    = Series(spec_mfi)                      # spec -> MFI
hits   = incompatible_donors[mfi.index]        # 0/1 matrix
burden = hits * mfi                            # MFI where DSA present

cum    = burden.sum(axis=1)
mx     = burden.max(axis=1)
n_dsa  = hits.sum(axis=1)
mean   = cum / n_dsa
med    = burden.where(hits.eq(1)).median(axis=1)   # NOT burden.median(axis=1)
```

The whole reference set is scored in one pass. Run twice (current, peak).

The new tool should extend the existing `Calculator` rather than replace it —
same ABO filter (once corrected per §4.1), same spec matching, same vocabulary.
The offered donor is scored by the identical function that scores the cohort.

### 6.2 DSA threshold

The MFI cutoff determines both which donors are incompatible and which
specificities enter the sums, so it propagates into every number. Make it a
visible parameter with the value printed in the output. Retain sub-threshold
pasted rows with a flag rather than dropping at ingest, so the threshold stays
adjustable after paste. For offers sitting near the boundary, consider showing
sensitivity to it.

### 6.3 Incomplete donor typing

For donors untyped at a locus the patient has antibodies against: return them as
a separate count. Do not silently exclude (shrinks the denominator unevenly) or
include (understates burden).

### 6.4 Sparse counts

Where counts are small — a handful of donors with lower burden — report the raw
count with a Wilson interval rather than a smooth-looking percentage, and refuse
a breakdown below a floor. The honest output there is *n donors observed, too
few to characterise*.

---

## 7. UI

### 7.1 Ingest

Bulk paste is a hard requirement — nobody will click forty specificities with two
MFI values each. The data already exists as an export from SAB analysis software.

Pattern: paste → detect delimiter (tab from Excel, comma from CSV) → per-column
role dropdown (specificity / current MFI / peak MFI / ignore) → preview with
problems flagged → commit. Column order must not be prescribed; every lab's
export differs.

Normalisation must be forgiving on the specificity string — case, whitespace,
`B*07` vs `B7`, `Cw6` vs `CW6`, `DPB1*04:01` vs `DPB4`. Unmatched tokens surface
as an explicit list for the user to resolve, never a silent discard. The
vocabulary is fixed and small, so fuzzy suggestion on unmatched tokens is cheap.

The same parser serves donor type entry — one parser, two entry points.

### 7.2 Assessment view

- Provenance strip fixed at the top: set, DP mode, cohort size, ABO rule, tier.
  Visible *before* any number is read.
- Current and peak within each metric panel, never on separate tabs — their
  divergence is the signal.
- Counts given equal visual weight to percentiles.
- Metric identity travels with the number. If someone screenshots "3rd
  percentile" it must be unambiguous which ordering produced it.
- DSA count shown alongside whichever metric is selected.

### 7.3 The DP toggle is not a display option

Switching DP mode changes three things at once: the reference set's size *and
membership*, the DSA set entering the arithmetic, and which donors count as
compatible at all. The two runs are not "before and after" — they are separate
assessments of the same offer on non-comparable scales.

So: put it in the provenance strip, not inline with display controls. When a
patient has DP specificities and exclude is selected, state what is being
discarded (*n* specificities removed, cRF x → y) rather than silently producing
a lower, official-looking number.

Open question worth deciding: should exclude even be offered when the patient has
DP antibodies, or gated behind something more deliberate? Reproducing an NHSBT
figure is legitimate but narrow, and it is the case where a wrong number is most
likely to be quoted onward.

---

## 8. Build order

1. Fix untyped-vs-zero in the DP columns (§3.1). Everything else sits on top.
2. Correct the ABO reference population to the offerable set (§4.1).
3. Parser and normalisation layer (§7.1) — self-contained, testable without the
   cohort, and it decides whether the tool is usable in practice.
4. Burden metrics over the incompatible set (§6.1), with synthetic verification
   cases (§3.3).
5. Placement and counts (§2.3).
6. Representativeness check on the 3.6k subset (§3.2).
7. Mismatch level and the joint view (§2.4).
8. Replication across the three sets on defined profile–donor pairs (§3.3).
9. API surface (§5), then dashboard (§7.2).

---

## 9. Open questions

- Does burden distribution shape actually hold across ABO strata? (§4.1)
- Is the 3.6k DP-typed subset representative? (§3.2)
- Does locus matter to burden — is a DQ DSA at MFI 8,000 the same problem as a
  C DSA at 8,000? Clinical judgement, currently unmodelled.
- Raw MFI axis or rank axis for the distribution plots? Raw is more
  interpretable but heavily right-skewed, compressing the interesting left tail.
- Should DP exclusion be gated for DP-antibody patients? (§7.3)
