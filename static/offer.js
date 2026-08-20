/* offer assessment page
 *
 * Two calls, mirroring the API: the profile builds the distributions, the donor
 * is placed against them. Counts are given at least equal weight to percentiles
 * throughout, and the metric identity travels with every number so a screenshot
 * of "3rd percentile" is never ambiguous about which ordering produced it.
 *
 * Copy rule: the page says "antibody load" where the API says "burden". The
 * reader is a mixed audience -- clinician, scientist, and non-specialist -- and
 * only the first two know what burden means here. The API field names are shown
 * alongside in the detail panels so a screenshot still maps onto the JSON.
 *
 * Layout rule: one plain answer is always visible; everything else lives in a
 * <details> panel and is closed until asked for. Nothing is deleted, because the
 * disagreement between measures is itself a finding.
 */

/* UK (NHSBT) tissue-match levels, from B and DR broad mismatch counts. These
 * are scheme-specific and mean nothing outside it, so the mismatch counts
 * behind each level travel with the number. Mirrors GRADE_LEVELS in
 * api/calculator.py -- if that changes, this must follow. */
const MISMATCH_LEVEL_DETAIL = {
  1: '0 DR, 0-1 B mismatches',
  2: '1 DR, 0 B mismatches',
  3: '0 DR 2 B, or 1 DR 1 B',
  4: '1 DR 2 B, or 2 DR',
};

const METRIC_LABELS = {
  cumulative: 'Total load',
  max: 'Strongest single antibody',
  mean: 'Average per antibody',
  median: 'Typical antibody',
};

/* Short enough to sit under the metric name without wrapping. The full
 * definitions, with the API field names, are in the measures drawer. */
const METRIC_DEFINITIONS = {
  cumulative: 'sum of all',
  max: 'strongest',
  mean: 'average',
  median: 'middle value',
};

const METRIC_ORDER = ['cumulative', 'max', 'mean', 'median'];

/* Peak before current, matching the preview table and the metric cards. The
 * server detects roles from the header text rather than position, so a paste in
 * either order parses correctly -- this is presentation only. */
const ROLE_LABELS = {
  spec: 'Specificity',
  peak_mfi: 'Peak MFI',
  current_mfi: 'Current MFI',
  ignore: 'Ignore',
};

const state = {
  rows: [],
  roles: null,
  columns: [],
  lastText: '',
  valid: false,
  parseGeneration: 0,
  assessmentGeneration: 0,
  parseTimer: null,
};

const $ = (id) => document.getElementById(id);
const fmt = (n) => (n === null || n === undefined ? '—' : n.toLocaleString());
const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function errorMessage(payload, fallback) {
  if (!payload) return fallback;
  if (typeof payload.detail === 'string') return payload.detail;
  if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg).join('; ');
  return fallback;
}

async function responseJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

function showAssessmentError(message) {
  const container = $('assessment-error');
  container.innerHTML = '';
  if (!message) return;
  const error = document.createElement('div');
  error.className = 'problem error mt-2';
  error.textContent = message;
  container.appendChild(error);
}

// ---------------------------------------------------------------------------
// parsing
// ---------------------------------------------------------------------------

async function parsePaste(useRoles) {
  const text = $('paste-box').value;
  if (!text.trim()) return;
  const generation = ++state.parseGeneration;
  state.lastText = text;

  const body = { text };
  if (useRoles && state.roles) body.roles = state.roles;

  let response;
  try {
    response = await fetch('/offer/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (_error) {
    if (generation === state.parseGeneration) renderProblems([{ message: 'Unable to parse the profile.' }]);
    return;
  }
  const result = await responseJson(response);
  if (generation !== state.parseGeneration) return;
  if (!response.ok || !result) {
    state.valid = false;
    renderProblems([{ message: errorMessage(result, 'Unable to parse the profile.') }]);
    updateAssessButton();
    return;
  }

  state.rows = result.rows;
  state.roles = result.roles;
  state.columns = result.columns;
  state.valid = result.ok;

  renderRoles(result);
  renderPreview(result);
  renderProblems(result.problems);
  updateAssessButton();
}

function renderRoles(result) {
  const container = $('role-selectors');
  container.innerHTML = '';
  if (!result.roles || !result.roles.length) {
    $('role-row').classList.add('d-none');
    return;
  }
  $('role-row').classList.remove('d-none');

  result.roles.forEach((role, index) => {
    const wrapper = document.createElement('div');
    const label = result.columns[index] || `Column ${index + 1}`;

    const select = document.createElement('select');
    select.className = 'form-select form-select-sm';
    select.style.minWidth = '9rem';
    Object.entries(ROLE_LABELS).forEach(([value, text]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      if (value === role) option.selected = true;
      select.appendChild(option);
    });
    select.addEventListener('change', () => {
      state.roles[index] = select.value;
      parsePaste(true);
    });

    const caption = document.createElement('div');
    caption.className = 'small text-muted text-truncate';
    caption.style.maxWidth = '9rem';
    caption.textContent = label;

    wrapper.appendChild(select);
    wrapper.appendChild(caption);
    container.appendChild(wrapper);
  });
}

function renderPreview(result) {
  const body = $('preview-body');
  body.innerHTML = '';
  if (!result.rows.length) {
    $('preview').classList.add('d-none');
    return;
  }
  $('preview').classList.remove('d-none');

  result.rows.forEach((row) => {
    const tr = document.createElement('tr');
    if (!row.recognised) tr.className = 'unrecognised';

    const spec = document.createElement('td');
    if (row.recognised) {
      spec.textContent = row.spec;
      // show the raw token when normalisation changed it, so the user can see
      // what the tool decided their paste meant
      if (row.raw_spec.toUpperCase() !== row.spec) {
        const raw = document.createElement('span');
        raw.className = 'raw-token ms-1';
        raw.textContent = `(${row.raw_spec})`;
        spec.appendChild(raw);
      }
    } else {
      const struck = document.createElement('s');
      struck.textContent = row.raw_spec;
      spec.appendChild(struck);
    }

    const current = document.createElement('td');
    current.className = 'text-end';
    current.textContent = fmt(row.current);

    const peak = document.createElement('td');
    peak.className = 'text-end';
    peak.textContent = fmt(row.peak);

    // Peak before current, matching the metric cards and the column headers.
    tr.append(spec, peak, current);
    body.appendChild(tr);
  });

  const recognised = result.rows.filter((r) => r.recognised).length;
  $('spec-count').textContent = `${recognised} specificit${recognised === 1 ? 'y' : 'ies'}`;
}

function renderProblems(problems) {
  const container = $('problems');
  container.innerHTML = '';
  problems.forEach((problem) => {
    const div = document.createElement('div');
    const isError = ['unrecognised_specificity', 'no_spec_column', 'no_current_mfi'].includes(problem.kind);
    div.className = `problem${isError ? ' error' : ''}`;
    div.textContent = problem.message;

    // unmatched tokens come back with suggestions -- the vocabulary is small,
    // so offering them is cheap and beats making the user hunt
    (problem.suggestions || []).forEach((suggestion) => {
      const button = document.createElement('button');
      button.className = 'btn btn-sm btn-outline-dark suggestion-btn';
      button.textContent = suggestion;
      button.addEventListener('click', () => {
        $('paste-box').value = $('paste-box').value.replace(
          new RegExp(`\\b${escapeRegExp(problem.token)}\\b`), suggestion);
        parsePaste(true);
      });
      div.appendChild(button);
    });
    container.appendChild(div);
  });
}

// ---------------------------------------------------------------------------
// assessment
// ---------------------------------------------------------------------------

function profilePayload() {
  const threshold = Number.parseFloat($('threshold').value);
  return {
    bg: $('bg').value,
    specs: state.rows
      .filter((r) => r.recognised && r.current !== null)
      .map((r) => ({ spec: r.spec, current: r.current, peak: r.peak })),
    dp_mode: $('dp-mode').value,
    threshold: Number.isFinite(threshold) ? threshold : 2000,
  };
}

function updateAssessButton() {
  const hasSpecs = state.rows.some((r) => r.recognised && r.current !== null);
  const hasDonor = $('donor-hla').value.trim().length > 0;
  const aboSupported = $('donor-bg').value === $('bg').value;
  $('btn-assess').disabled = !(state.valid && hasSpecs && hasDonor && aboSupported);
  if (!aboSupported) {
    showAssessmentError('Blood groups must match — cross-group rules not yet built in.');
  }
}

function setAssessmentBusy(busy) {
  $('btn-assess').disabled = busy
    || !state.valid
    || !$('donor-hla').value.trim()
    || $('donor-bg').value !== $('bg').value;
  $('assess-label').textContent = busy ? 'Assessing…' : 'Assess offer';
  $('btn-assess').setAttribute('aria-busy', busy ? 'true' : 'false');
}

function finishAssessment(generation) {
  if (generation === state.assessmentGeneration) setAssessmentBusy(false);
}

async function assess() {
  const generation = ++state.assessmentGeneration;
  showAssessmentError('');
  setAssessmentBusy(true);
  const donorText = $('donor-hla').value.trim();
  let donorResponse;
  try {
    donorResponse = await fetch('/offer/parse-donor', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: donorText }),
    });
  } catch (_error) {
    if (generation === state.assessmentGeneration) showAssessmentError('Unable to validate the donor HLA type.');
    finishAssessment(generation);
    return;
  }
  const donorResult = await responseJson(donorResponse);
  if (generation !== state.assessmentGeneration) return;

  if (!donorResponse.ok || !donorResult || (donorResult.problems || []).length) {
    $('donor-parse').textContent = donorResult?.problems?.map((problem) => problem.message).join('; ')
      || errorMessage(donorResult, 'Unable to validate the donor HLA type.');
    $('donor-parse').classList.add('text-danger');
    finishAssessment(generation);
    return;
  }
  $('donor-parse').classList.remove('text-danger');
  $('donor-parse').textContent = `Read as: ${donorResult.antigens.join(', ')}`;

  const payload = {
    ...profilePayload(),
    donor_hla: donorResult.antigens,
    donor_bg: $('donor-bg').value,
  };
  const recipHla = $('recip-hla').value.trim();
  if (recipHla) payload.recip_hla = recipHla;

  let response;
  try {
    response = await fetch('/offer/placement', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (_error) {
    if (generation === state.assessmentGeneration) showAssessmentError('Unable to calculate the offer assessment.');
    finishAssessment(generation);
    return;
  }

  if (!response.ok) {
    const error = await responseJson(response);
    if (generation === state.assessmentGeneration) showAssessmentError(errorMessage(error, 'Assessment failed.'));
    finishAssessment(generation);
    return;
  }

  const result = await responseJson(response);
  if (!result) {
    if (generation === state.assessmentGeneration) showAssessmentError('The assessment returned an unreadable response.');
    finishAssessment(generation);
    return;
  }
  if (generation === state.assessmentGeneration) {
    render(result);
    // close the drawer so the results it produced are actually on screen
    const drawer = bootstrap.Offcanvas.getInstance($('drawer-input'));
    if (drawer) drawer.hide();
  }
  finishAssessment(generation);
}

// ---------------------------------------------------------------------------
// rendering results
// ---------------------------------------------------------------------------

function render(result) {
  $('placeholder').classList.add('d-none');
  $('results').classList.remove('d-none');
  updateInputSummary(result);

  const current = result.basis_summaries.current;
  renderProvenance(result.meta, current);
  $('hl-dsa').textContent = current.dsa_count;
  $('hl-ref').textContent = fmt(current.reference_size);
  $('hl-same').textContent = fmt(current.identical_dsa_set_count);
  renderDsaSpecs(current.dsa_specs);
  renderWhatThisMeans(result, current);
  renderPrimary(result, current);
  renderMetrics(result);
  renderJoint(result.joint);
}

function renderDsaSpecs(specs) {
  const container = $('hl-specs');
  container.innerHTML = '';
  if (!specs.length) {
    const none = document.createElement('span');
    none.className = 'text-success';
    none.textContent = 'None of this patient\'s antibodies hit this donor at the selected strength.';
    container.appendChild(none);
    return;
  }
  specs.forEach((spec) => {
    const badge = document.createElement('span');
    badge.className = 'spec-badge';
    badge.textContent = spec;
    container.appendChild(badge);
  });
}

function renderWhatThisMeans(result, summary) {
  const reference = $('glossary-reference');
  const cohort = result.cohort_placements?.current;
  reference.textContent = cohort
    ? `Every one of the ${fmt(cohort.cohort_size)} donors this patient could be offered — including the `
      + `${fmt(cohort.n_compatible)} that carry none of their antibodies. Those are counted as better offers, `
      + 'because a donor needing no antibody treatment is a better outcome than one that does.'
    : 'Every donor this patient could be offered.';

  const specs = $('drawer-case');
  if (!specs) return;
  specs.innerHTML = '';
  if (!summary.dsa_specs.length) return;

  const heading = document.createElement('div');
  heading.className = 'drawer-case-heading';
  heading.textContent = summary.dsa_specs.length === 1
    ? 'One antibody hits this donor'
    : `${summary.dsa_specs.length} antibodies hit this donor`;
  specs.appendChild(heading);

  const badges = document.createElement('div');
  badges.className = 'drawer-case-badges';
  summary.dsa_specs.forEach((spec) => {
    const badge = document.createElement('span');
    badge.className = 'spec-badge';
    badge.textContent = spec;
    badges.appendChild(badge);
  });
  specs.appendChild(badges);

  if (summary.dsa_specs.length === 1) {
    const note = document.createElement('p');
    note.className = 'detail-note mt-2 mb-0';
    note.textContent = 'Every donor carrying it scores the same, so a ranking among incompatible donors '
      + 'cannot separate them.';
    specs.appendChild(note);
  }
}

function renderPrimary(result, summary) {
  const status = $('summary-status');
  const visual = $('ranking-visual');
  const metricCard = $('detail-measures');
  status.className = 'badge mb-2';

  if (summary.status !== 'ranked_incompatible') {
    visual.classList.add('d-none');
    metricCard.classList.toggle('d-none', Object.keys(result.placements).length === 0);
    // clear the previous offer's counts: the visual is hidden but the numbers
    // remain in the DOM, and a later assessment must not inherit them
    ['summary-lower', 'summary-equal', 'summary-higher'].forEach((id) => {
      $(id).textContent = '—';
      const pct = $(`${id}-pct`);
      if (pct) pct.textContent = '';
    });
    $('summary-bar').innerHTML = '';
    $('summary-facts').innerHTML = '';
    $('bar-braces').innerHTML = '';
    if (summary.status === 'compatible_no_dsa') {
      status.classList.add('text-bg-success');
      status.textContent = 'Compatible';
      $('summary-title').textContent = 'No antibody against this donor';
    } else if (summary.status === 'no_active_specificities') {
      status.classList.add('text-bg-warning');
      status.textContent = 'Nothing counted';
      $('summary-title').textContent = 'No antibodies above the MFI cut-off';
    } else {
      status.classList.add('text-bg-warning');
      status.textContent = 'No comparison';
      $('summary-title').textContent = 'No comparable donors on record';
    }
    return;
  }

  visual.classList.remove('d-none');
  metricCard.classList.remove('d-none');
  // Left open: the results column otherwise ended ~350px above the input
  // column, which read as unfinished. These are data, not prose.
  metricCard.open = true;

  // Cohort-wide is the primary reading: it includes the compatible donors, which
  // are unambiguously better offers and which the incompatible-only reference
  // silently discards. Fall back only if the server could not compute it.
  const cohort = result.cohort_placements?.current;
  if (cohort) {
    renderCohortPrimary(result, cohort, status);
    return;
  }
  const placement = result.placements['current:cumulative'];
  // Same source of truth as the bar marker, so the badge and the mark it sits
  // above cannot end up telling different stories.
  const badgeTone = {
    'offer-marker-low': 'text-bg-success',
    'offer-marker-mid': 'text-bg-primary',
    'offer-marker-high': 'text-bg-danger',
  };
  status.classList.add(badgeTone[offerToneClass(placement)]);
  status.textContent = 'Antibody load against this donor';
  $('summary-title').textContent = positionTitle(placement);
  renderCounts(placement);
  renderRankStack($('summary-bar'), placement);
  renderRankLabels(placement);

  // No brace row here: this path has only the incompatible population, so there
  // are not two groups to name.
  $('bar-braces').innerHTML = '';

  const facts = $('summary-facts');
  facts.innerHTML = '';
  const entries = [[fmt(Math.round(placement.value)), 'total MFI vs this donor']];
  if (placement.empirical_percentile_range) {
    const [low, high] = placement.empirical_percentile_range;
    entries.push([`${low.toFixed(0)}–${high.toFixed(0)}%`, 'of incompatible donors carry less']);
  } else {
    entries.push([fmt(placement.reference_size), 'donors compared — too few for a %']);
  }
  entries.forEach(([value, label]) => {
    const fact = document.createElement('div');
    fact.className = 'verdict-fact';
    const strong = document.createElement('span');
    strong.className = 'verdict-fact-value';
    strong.textContent = value;
    const small = document.createElement('span');
    small.className = 'verdict-fact-label';
    small.textContent = label;
    fact.append(strong, small);
    facts.appendChild(fact);
  });
}

/* The offer against every donor the patient could be offered.
 *
 * The earlier version ranked only within incompatible donors, which answers a
 * different question than the one the tool exists for. For a patient with one
 * DSA that reference is ~27% of the cohort and every donor it drops is a
 * compatible -- i.e. better -- offer. Reporting "all similar" over that subset
 * was true and useless. */
function renderCohortPrimary(result, cohort, status) {
  const tone = cohortToneClass(cohort);
  status.classList.add({
    'offer-marker-low': 'text-bg-success',
    'offer-marker-mid': 'text-bg-primary',
    'offer-marker-high': 'text-bg-danger',
  }[tone]);
  status.textContent = 'Antibody load against this donor';

  $('summary-title').textContent = cohortTitle(cohort);
  const shape = {
    n_lower: cohort.n_lower,
    n_equal: cohort.n_equal,
    n_higher: cohort.n_higher,
    reference_size: cohort.cohort_size,
  };
  // Shares are of the whole cohort here, not the incompatible subset: that is
  // the denominator the bar and the headline already use.
  renderCounts(shape);
  renderRankStack($('summary-bar'), shape, tone);
  renderRankLabels(shape);
  renderBraces(cohort);
  renderFacts(cohort);
}

/* A brace under the bar naming the two populations it is made of. This is the
 * "73% carry no antibody" fact drawn rather than written -- the span of the
 * brace *is* the proportion, so the number and the picture cannot disagree. */
function renderBraces(cohort) {
  const braces = $('bar-braces');
  braces.innerHTML = '';
  if (!cohort.cohort_size) return;

  const compatibleShare = cohort.n_compatible / cohort.cohort_size;
  // Mirrors the bar: the incompatible donors are drawn on the left now, so the
  // brace naming them has to lead.
  const groups = [
    [1 - compatibleShare, `${fmt(cohort.n_incompatible)} some antibody`, 'brace-incompatible'],
    [compatibleShare, `${fmt(cohort.n_compatible)} no antibody`, 'brace-compatible'],
  ];
  groups.forEach(([share, label, className]) => {
    if (share <= 0) return;
    const group = document.createElement('span');
    group.className = `bar-brace ${className}`;
    group.style.width = `${share * 100}%`;
    const text = document.createElement('span');
    text.className = 'bar-brace-label';
    text.textContent = label;
    group.appendChild(text);
    braces.appendChild(group);
  });

  // A brace too narrow to hold its own caption lets it hang off the edge
  // rather than truncating it to "105 n...".
  [...braces.children].forEach((group) => {
    const label = group.querySelector('.bar-brace-label');
    if (label && label.scrollWidth > group.clientWidth) group.classList.add('is-narrow');
  });
}

/* Two figures, not a sentence. Everything else the paragraph used to say is
 * already on screen as a number or a bar segment. */
function renderFacts(cohort) {
  const facts = $('summary-facts');
  facts.innerHTML = '';
  [
    [`${fmt(Math.round(cohort.value))}`, 'total MFI vs this donor'],
    [`${cohort.compatible_share.toFixed(0)}%`, 'need no antibody treatment'],
  ].forEach(([value, label]) => {
    const fact = document.createElement('div');
    fact.className = 'verdict-fact';
    const strong = document.createElement('span');
    strong.className = 'verdict-fact-value';
    strong.textContent = value;
    const small = document.createElement('span');
    small.className = 'verdict-fact-label';
    small.textContent = label;
    fact.append(strong, small);
    facts.appendChild(fact);
  });
}

/* Title and tone read from one band so they cannot disagree -- an earlier cut
 * had a blue badge sitting over a "worse than most" headline, because the two
 * used different cut-offs. Bands are on the share of the WHOLE cohort that beats
 * this offer: an offer can sit at the bottom of the incompatible range and still
 * be worse than three quarters of what the patient could be offered. */
function cohortBand(cohort) {
  if (!cohort.cohort_size) return 'mid';
  const share = cohort.n_lower / cohort.cohort_size;
  if (cohort.n_lower === 0) return 'best';
  if (share <= 0.1) return 'low';
  if (share < 0.5) return 'lowish';
  if (share >= 0.9) return 'worst';
  if (share > 0.5) return 'high';
  return 'mid';
}

function cohortToneClass(cohort) {
  return {
    best: 'offer-marker-low',
    low: 'offer-marker-low',
    lowish: 'offer-marker-mid',
    mid: 'offer-marker-mid',
    high: 'offer-marker-high',
    worst: 'offer-marker-high',
  }[cohortBand(cohort)];
}

function cohortTitle(cohort) {
  return {
    best: 'As good as this patient could be offered',
    low: 'Better than almost every donor on offer',
    lowish: 'Better than most donors on offer',
    mid: 'About average for this patient',
    high: 'Worse than most donors on offer',
    worst: 'Worse than almost every donor on offer',
  }[cohortBand(cohort)];
}

function positionTitle(placement) {
  // All-tie first: with one specificity every incompatible donor scores the
  // same, and n_lower is 0 for a reason that is not "this offer is good".
  // Claiming "one of the easiest" there contradicts the body copy, which
  // correctly says the comparison cannot separate them.
  if (placement.n_equal === placement.reference_size) return 'This comparison cannot separate the donors';
  if (placement.n_lower === 0) return 'One of the easiest offers this patient could get';
  const share = placement.n_lower / placement.reference_size;
  if (share <= 0.1) return 'Easier than almost every other donor';
  if (share <= 0.25) return 'Easier than most other donors';
  if (share >= 0.9) return 'Harder than almost every other donor';
  if (share >= 0.75) return 'Harder than most other donors';
  return 'About average for this patient';
}

/* Two encodings on one bar read backwards: colouring "donors better than this
 * offer" green made a *bad* offer show a long green bar, because length says
 * "how many" while colour said "good". Length and colour were fighting, and
 * length won.
 *
 * So they are separated. The bar is a neutral population: segment length means
 * how many donors, nothing else. Colour is spent on one thing only -- a marker
 * for where THIS offer sits, green at the low-load end and red at the high-load
 * end. The single coloured element is the one the reader is actually judging,
 * and it agrees with the status badge above it. */
function renderRankStack(container, placement, toneClass) {
  container.innerHTML = '';
  const total = placement.reference_size || 0;
  // Worse on the left, better on the right: the axis runs from heavy load to
  // light, so moving rightwards means a better offer. Segment order, marker
  // position, braces and captions all encode this one direction and are flipped
  // together -- reversing only the paint would leave the marker on the wrong band.
  const groups = [
    ['higher', placement.n_higher, 'carry more antibody load than this offer'],
    ['equal', placement.n_equal, 'carry the same antibody load as this offer'],
    ['lower', placement.n_lower, 'carry less antibody load than this offer'],
  ];
  groups.forEach(([name, count, wording]) => {
    const segment = document.createElement('span');
    segment.className = `rank-segment rank-segment-${name}`;
    segment.style.width = `${total ? (count / total) * 100 : 0}%`;
    segment.title = `${fmt(count)} donors ${wording}`;
    container.appendChild(segment);
  });

  // Centre of the tie band, not its edge. Every donor in that band scores
  // identically, so the offer has no rank within it -- parking the marker on
  // the left edge implied it was the lightest of the tied group, which is a
  // position the data does not support.
  //
  // The all-tie case is the clearest test: when every donor ties the marker
  // lands dead centre, which is exactly the claim being made (no position at
  // all). An earlier cut used the edge to stop a green marker appearing mid-bar
  // under "one of the easiest offers" -- but that was a headline bug, and the
  // headline is now decided separately by cohortBand().
  const marker = document.createElement('span');
  const position = total ? (placement.n_higher + placement.n_equal / 2) / total : 0;
  marker.className = `offer-marker ${toneClass || offerToneClass(placement)}`;
  // Kept a hair inside the track so an offer at either extreme still shows a
  // whole marker rather than half of one bleeding over the border.
  marker.style.left = `${Math.min(99, Math.max(1, position * 100))}%`;
  marker.title = placement.n_equal
    ? `This offer, with ${fmt(placement.n_equal)} donors carrying exactly the same load. `
      + `${fmt(placement.n_higher)} carry more, ${fmt(placement.n_lower)} carry less.`
    : `This offer: ${fmt(placement.n_higher)} donors carry more load, ${fmt(placement.n_lower)} carry less`;
  container.appendChild(marker);

  container.setAttribute(
    'aria-label',
    `This offer carries less antibody load than ${fmt(placement.n_higher)} of ${fmt(total)} donors compared, `
    + `more than ${fmt(placement.n_lower)}, and the same as ${fmt(placement.n_equal)}.`,
  );
}

/* The offer's own tone, on the same thresholds as the status badge so the two
 * can never disagree on screen. A high n_lower means most donors are better
 * than this offer, which is the unfavourable end. */
function offerToneClass(placement) {
  if (!placement.reference_size) return 'offer-marker-mid';
  // Everything tied: there is no position to judge, so the marker takes the
  // neutral tone rather than implying a favourable one.
  if (placement.n_equal === placement.reference_size) return 'offer-marker-mid';
  const share = placement.n_lower / placement.reference_size;
  if (share <= 0.1) return 'offer-marker-low';
  if (share >= 0.75) return 'offer-marker-high';
  return 'offer-marker-mid';
}

/* Counts and their share of the reference population, written together so the
 * two can never describe different denominators -- the incompatible-only path
 * and the whole-cohort path use different ones. Rounded to whole percent
 * except where that would print a misleading 0%% for a non-empty group. */
function renderCounts(shape) {
  const total = shape.reference_size || 0;
  [
    ['summary-higher', shape.n_higher],
    ['summary-equal', shape.n_equal],
    ['summary-lower', shape.n_lower],
  ].forEach(([id, count]) => {
    $(id).textContent = fmt(count);
    const pct = $(`${id}-pct`);
    if (!pct) return;
    if (!total || !count) {
      // A zero group is already stated by the count; "0%" adds nothing.
      pct.textContent = '';
      return;
    }
    const share = (count / total) * 100;
    if (share < 1) {
      // A non-empty group is never "0%": the count above it says otherwise.
      pct.textContent = '<1%';
    } else if (share > 99 && count < total) {
      // Nor is it "100%" while another group is visibly non-empty -- 99.98%
      // rounds up and reads as a contradiction against the sliver beside it.
      pct.textContent = '>99%';
    } else {
      pct.textContent = `${Math.round(share)}%`;
    }
  });
}

/* Remembered so a resize can redraw without a fresh assessment. */
let lastPlacement = null;

/* Labels track the bar's proportions so the numbers sit under the segment they
 * describe. A zero group is hidden rather than shrunk to an unreadable sliver.
 *
 * That alignment only works while every segment is wide enough to sit a label
 * under. At lopsided splits it is not: 4,372 / 143 / 105 puts two labels over
 * segments about 3% of the track wide, and the eye cannot tell which number
 * belongs to which sliver. Past that point the labels drift to their segments
 * and leader lines carry the link instead -- see driftRankLabels(). */
function renderRankLabels(placement) {
  const counts = [placement.n_higher, placement.n_equal, placement.n_lower];
  const container = $('summary-counts');
  const visible = counts.filter((count) => count > 0).length;
  // The floor stops a lopsided split squeezing a count into a tower of wrapped
  // characters. It has to be expressed against the row's real width: `min(7rem,
  // 100%)` resolved the percentage against the column, not the row, so three
  // 7rem floors could demand 336px inside a 303px row and overflow the card.
  const rowWidth = container.getBoundingClientRect().width;
  const floorRem = visible > 1 ? Math.min(7, 22 / visible) : 0;
  const floorPx = rowWidth
    ? Math.min(floorRem * 16, rowWidth / visible)
    : floorRem * 16;
  const floor = `${floorPx}px`;

  // The proportional grid is still the layout of record. Drift is measured
  // against it, and reverting is just clearing the drift class.
  container.classList.remove('is-drifted');
  container.style.removeProperty('height');
  container.style.gridTemplateColumns = counts
    .map((count) => (count === 0 ? '0px' : `minmax(${floor}, ${count}fr)`))
    .join(' ');
  [...container.children].forEach((label, index) => {
    label.classList.toggle('is-empty', counts[index] === 0);
    label.style.removeProperty('left');
  });

  lastPlacement = placement;
  driftRankLabels(placement);
}

/* How wide a label wants to be, independent of the column it currently sits
 * in. Neither the rendered box nor scrollWidth can answer this: the
 * proportional grid stretches the big group to its full share (1,499px for a
 * "4,372" that needs about 90) and squeezes the thin ones, so both report the
 * space given rather than the space needed. Cloning it out of the grid with
 * max-content sizing measures the text itself. */
function naturalWidth(group) {
  const probe = group.cloneNode(true);
  probe.style.cssText = 'position:absolute;visibility:hidden;width:max-content;'
    + 'max-width:none;left:-9999px;top:0;padding:0;';
  probe.classList.remove('is-empty');
  group.parentNode.appendChild(probe);
  const measured = probe.getBoundingClientRect().width;
  probe.remove();
  return measured;
}

/* Gap kept between two drifted labels. The labels' own widths are measured;
 * this is only the breathing space between them. */
const LABEL_GAP_PX = 10;

function driftRankLabels(placement) {
  const container = $('summary-counts');
  const bar = $('summary-bar');
  const svg = $('rank-leaders');
  if (!container || !bar || !svg) return;

  svg.innerHTML = '';
  svg.style.removeProperty('--leader-h');

  const counts = [placement.n_higher, placement.n_equal, placement.n_lower];
  const total = placement.reference_size || 0;
  const width = bar.getBoundingClientRect().width;
  if (!total || !width) return;

  // Segment centres in bar-local pixels, walking the same order the stack is
  // painted in so a label can never point at the wrong band.
  let cursor = 0;
  const centres = counts.map((count) => {
    const segWidth = (count / total) * width;
    const centre = cursor + segWidth / 2;
    cursor += segWidth;
    return { centre, segWidth };
  });

  const groups = [...container.children];
  // Measured, not assumed: "SIMILAR" and "BETTER" are wider than the numbers
  // above them, and a guessed constant let them overlap at the bar's edge.
  const widths = groups.map(naturalWidth);
  const active = counts
    .map((count, index) => ({
      index, count, ...centres[index], width: widths[index],
    }))
    .filter((item) => item.count > 0);
  if (!active.length) return;

  // Every label already has room over its own segment: the proportional grid
  // reads correctly, so leave it be rather than adding furniture.
  if (active.every((item) => item.segWidth >= item.width)) return;

  // Drift needs somewhere to drift to. On a narrow bar the labels cannot be
  // separated on one row at any offset, and forcing it just re-creates the
  // overlap it exists to prevent. The proportional grid wraps and shrinks
  // instead, so below this threshold it is the better of the two layouts.
  //
  // The comparison is against the row the labels actually occupy, which is the
  // bar's own width -- they are positioned in its coordinate space, so a label
  // pushed beyond it would hang outside the card.
  const needed = active.reduce((sum, item) => sum + item.width, 0)
    + LABEL_GAP_PX * (active.length - 1);
  if (needed > width) return;

  const placed = active.map((item) => ({ ...item, x: item.centre }));

  // Push right so no two labels overlap...
  for (let i = 1; i < placed.length; i += 1) {
    const minX = placed[i - 1].x + (placed[i - 1].width + placed[i].width) / 2 + LABEL_GAP_PX;
    if (placed[i].x < minX) placed[i].x = minX;
  }
  // ...then, if that pushed the run off the right edge, lay the whole run back
  // leftwards from the edge. Walking pairwise instead would let an earlier
  // label be dragged back into the one behind it, which is precisely how
  // 143 and 105 ended up printed as "143105".
  const last = placed[placed.length - 1];
  const overflow = last.x + last.width / 2 - width;
  if (overflow > 0) {
    for (let i = placed.length - 1; i >= 0; i -= 1) {
      placed[i].x -= overflow;
      if (i > 0) {
        const maxX = placed[i].x - (placed[i].width + placed[i - 1].width) / 2 - LABEL_GAP_PX;
        if (placed[i - 1].x > maxX) placed[i - 1].x = maxX;
      }
    }
  }
  // Never let the leftmost label hang off the near edge either.
  if (placed[0].x - placed[0].width / 2 < 0) placed[0].x = placed[0].width / 2;

  // The two clamps above can, on a tight row, leave a pair overlapping again.
  // Rather than ship a layout the algorithm knows is broken, fall back to the
  // proportional grid, which shrinks and wraps instead of colliding.
  for (let i = 1; i < placed.length; i += 1) {
    const gap = placed[i].x - placed[i].width / 2
      - (placed[i - 1].x + placed[i - 1].width / 2);
    if (gap < 0) return;
  }

  container.classList.add('is-drifted');
  placed.forEach((item) => {
    groups[item.index].style.left = `${(item.x / width) * 100}%`;
  });

  // Absolute children leave no height behind, so the row would collapse and
  // the facts beneath it would ride up over the labels.
  const tallest = Math.max(...placed.map((item) => groups[item.index].offsetHeight), 0);
  container.style.height = `${tallest}px`;

  drawLeaders(placed, width);
}

/* One elbow per drifted label: down from the segment, across, then down to the
 * label. Drawn in the gap between the bar and the counts row, which is exactly
 * the span the overlay covers. */
function drawLeaders(placed, width) {
  const svg = $('rank-leaders');
  const bar = $('summary-bar');
  const container = $('summary-counts');
  const visual = $('ranking-visual');

  const visualBox = visual.getBoundingClientRect();
  const barBox = bar.getBoundingClientRect();
  const countsBox = container.getBoundingClientRect();

  // A leader has to start at the segment it names, so the overlay spans the
  // whole bar-to-counts gap. The axis captions live in that gap but only at its
  // two far ends, so lines are suppressed where they would cross that text
  // rather than being started below it -- a line beginning in empty space
  // points at nothing.
  const top = barBox.bottom - visualBox.top;
  const height = countsBox.top - barBox.bottom;
  // Braces and axis captions occupy this gap too; if it has collapsed there is
  // nowhere to draw and a cramped line would only add noise.
  if (height <= 4) return;

  svg.style.top = `${top}px`;
  svg.style.setProperty('--leader-h', `${height}px`);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.setAttribute('preserveAspectRatio', 'none');

  // The captions sit at the two far ends of this same gap. Rather than drop a
  // leader that would cross them -- which loses the connection for exactly the
  // label that most needs it -- the line is drawn behind them and the caption
  // is given an opaque backdrop, so the stroke reads as passing beneath text.
  placed.forEach((item) => {
    // A label that barely moved reads fine on alignment alone; a line there is
    // clutter.
    if (Math.abs(item.x - item.centre) < 4) return;
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    // Drop straight out of the segment, then angle across to the label: the
    // vertical stub is what ties the line to a specific band.
    const mid = height * 0.45;
    path.setAttribute(
      'd',
      `M ${item.centre} 0 L ${item.centre} ${mid} L ${item.x} ${height - 2}`,
    );
    path.setAttribute('class', 'rank-leader');
    path.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.appendChild(path);
  });
}

/* The whole layout is measured, so it has to be remeasured when the box
 * changes -- window resize, the input drawer opening, or a late font swap. */
if (window.ResizeObserver) {
  const observer = new ResizeObserver(() => {
    if (lastPlacement) driftRankLabels(lastPlacement);
  });
  const barEl = $('summary-bar');
  if (barEl) observer.observe(barEl);
}

function renderJoint(joint) {
  const card = $('joint-card');
  if (!joint || !joint.cells.length) {
    card.classList.add('d-none');
    return;
  }
  card.classList.remove('d-none');

  const body = $('joint-body');
  body.innerHTML = '';

  [1, 2, 3, 4].forEach((band) => {
    const tr = document.createElement('tr');
    const label = document.createElement('td');
    label.textContent = ['Lowest quarter', 'Second quarter', 'Third quarter', 'Highest quarter'][band - 1];
    tr.appendChild(label);

    [1, 2, 3, 4].forEach((level) => {
      const cell = joint.cells.find((c) => c.burden_band === band && c.mismatch_level === level);
      const td = document.createElement('td');
      const count = cell ? cell.count : 0;
      td.textContent = count ? count.toLocaleString() : '—';
      td.style.setProperty('--heat', joint.reference_size ? Math.min(0.75, count / joint.reference_size * 8) : 0);
      if (band === joint.offered_burden_band && level === joint.offered_mismatch_level) {
        td.classList.add('offered');
        td.title = 'The offered donor sits here';
        const marker = document.createElement('span');
        marker.className = 'offer-cell-marker';
        marker.textContent = 'Offer';
        td.appendChild(marker);
      }
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  // The finding, not the axes. "Load x tissue match" named what was crossed but
  // never the question, which is whether this patient could realistically do
  // better on both counts at once. That answer was a single number sitting
  // underneath a 16-cell grid.
  const total = joint.reference_size || 0;
  const better = joint.n_better_on_both ?? 0;
  const worse = joint.n_worse_on_both ?? 0;
  const tradeoff = Math.max(0, total - better - worse);

  const headline = $('joint-headline');
  headline.innerHTML = '';
  [
    [fmt(better), 'better on both antibody load and tissue match', 'joint-stat-good'],
    [fmt(worse), 'worse on both', 'joint-stat-bad'],
    [fmt(tradeoff), 'a trade-off \u2014 better on one, worse on the other', 'joint-stat-neutral'],
  ].forEach(([value, label, className]) => {
    const stat = document.createElement('div');
    stat.className = `joint-stat ${className}`;
    const big = document.createElement('span');
    big.className = 'joint-stat-value';
    big.textContent = value;
    const tag = document.createElement('span');
    tag.className = 'joint-stat-label';
    tag.textContent = label;
    stat.append(big, tag);
    headline.appendChild(stat);
  });

  const position = $('joint-position');
  position.textContent = `Of ${fmt(total)} donors this patient reacts to, `
    + `${fmt(better)} would be an improvement on both counts at once. `
    + `This offer sits in the ${['lowest', 'second', 'third', 'highest'][joint.offered_burden_band - 1]} `
    + `quarter for antibody load, at UK tissue-match level ${joint.offered_mismatch_level} of 4`
    + `${MISMATCH_LEVEL_DETAIL[joint.offered_mismatch_level] ? ` (${MISMATCH_LEVEL_DETAIL[joint.offered_mismatch_level]})` : ''}.`;
}

/* Provenance is split in two: a single always-visible line saying what the
 * comparison group is, and the full record inside the detail panel. Two
 * assessments run under different toggles are not comparable, so the line that
 * says which toggles were used must not be hidden behind a click. */
function renderProvenance(meta, summary) {
  const provenance = meta.provenance;
  const notes = meta.notes || [];

  const grid = $('prov-grid');
  grid.innerHTML = '';
  const fingerprint = meta.data_provenance?.donor_database_sha256;
  [
    ['Donor records', provenance.donor_set.replace('donors_', 'Set '), null],
    ['Comparison group', provenance.dp_typed_only
      ? `${fmt(provenance.cohort_size)} of ${fmt(provenance.set_size_before_dp)} donors`
      : `${fmt(provenance.cohort_size)} donors`, null],
    ['Blood group rule', provenance.abo_rule === 'identical'
      ? `Identical only (${provenance.donor_bgs.join(', ')})`
      : provenance.abo_rule, null],
    ['HLA-DP handling', describeDp(provenance), null],
    ['Antibody cut-off', `MFI ${fmt(meta.threshold)} or above`, null],
    ['Allocation tier', provenance.tier || 'not set', null],
    ['Data version', fingerprint ? fingerprint.slice(0, 10) : '—', fingerprint],
    ['Method version', meta.policy_version, null],
  ].forEach(([label, value, title]) => {
    const item = document.createElement('div');
    item.className = 'prov-cell';
    const key = document.createElement('span');
    key.className = 'prov-label';
    key.textContent = label;
    const val = document.createElement('span');
    val.className = 'prov-value';
    val.textContent = value;
    if (title) val.title = title;
    item.append(key, val);
    grid.appendChild(item);
  });

  const drawerNotes = $('drawer-notes');
  if (drawerNotes) drawerNotes.innerHTML = '';
  const notesBox = $('prov-notes');
  notesBox.innerHTML = '';
  let flagged = 0;
  notes.forEach((note) => {
    const div = document.createElement('div');
    const critical = note.includes('cannot be corroborated')
      || note.includes('too small')
      || note.includes('discarded')
      || note.includes('cannot discriminate');
    const warning = note.includes('restricted to blood-group-identical')
      || note.includes('not comparable')
      || note.includes('different incompatible reference populations');
    if (critical || warning) flagged += 1;
    div.className = `prov-note${critical ? ' critical' : warning ? ' warning' : ''}`;
    div.textContent = note;
    notesBox.appendChild(div);
    if (drawerNotes) drawerNotes.appendChild(div.cloneNode(true));
  });

  const flag = $('prov-flag-count');
  flag.classList.toggle('d-none', flagged === 0);
  flag.textContent = flagged === 1 ? '1 caveat' : `${flagged} caveats`;

  // A chip on the verdict card, so a caveat is visible without opening anything
  // but its text does not sit in the results column.
  const chip = $('caveat-chip');
  chip.classList.toggle('d-none', flagged === 0);
  $('caveat-count').textContent = flagged;
}

function describeDp(provenance) {
  if (provenance.dp_mode_requested === 'auto' && !provenance.patient_has_dp_specs) {
    return 'no DP antibodies';
  }
  if (provenance.dp_mode_applied === 'include') {
    return 'DP-typed only';
  }
  return 'DP set aside';
}

function renderMetrics(result) {
  const container = $('metric-panels');
  container.innerHTML = '';

  renderMetricAgreement(result);

  // The two basis columns are named once, at the top. Repeating PEAK and
  // CURRENT in all four rows made the column heading compete with the value
  // it sits above eight times over.
  const header = document.createElement('div');
  header.className = 'metric-row metric-head';
  header.appendChild(document.createElement('div'));
  ['Peak', 'Current'].forEach((label) => {
    const cell = document.createElement('div');
    cell.className = 'metric-head-label';
    cell.textContent = label;
    header.appendChild(cell);
  });
  container.appendChild(header);

  METRIC_ORDER.forEach((metric) => {
    const row = document.createElement('div');
    row.className = 'metric-row';

    const identity = document.createElement('div');
    identity.className = 'metric-identity';
    const name = document.createElement('strong');
    name.textContent = METRIC_LABELS[metric];
    const definition = document.createElement('span');
    definition.textContent = METRIC_DEFINITIONS[metric];
    identity.append(name, definition);
    row.appendChild(identity);
    // Peak first: it is the historic high-water mark, so reading left to right
    // follows the antibody down from its worst to where it stands today.
    row.appendChild(metricBasisCell('Peak', result.placements[`peak:${metric}`], result.basis_summaries.peak, result.peak_unavailable_reason));
    row.appendChild(metricBasisCell('Current', result.placements[`current:${metric}`], result.basis_summaries.current));
    container.appendChild(row);
  });
}

function metricBasisCell(label, placement, summary, unavailableReason) {
  const cell = document.createElement('div');
  cell.className = 'metric-basis-cell';
  // Kept for the narrow layouts: below 768px the two columns stack, so the
  // header above them no longer names anything and each cell says it again.
  const heading = document.createElement('div');
  heading.className = 'metric-basis-label';
  heading.textContent = label;
  cell.appendChild(heading);
  if (!summary) {
    const unavailable = document.createElement('div');
    unavailable.className = 'small text-muted';
    unavailable.textContent = unavailableReason || 'Unavailable';
    cell.appendChild(unavailable);
    return cell;
  }
  if (!placement) {
    const unavailable = document.createElement('div');
    unavailable.className = 'small text-muted';
    unavailable.textContent = summary.status === 'compatible_no_dsa' ? 'No antibody hits this donor' : 'Not available';
    cell.appendChild(unavailable);
    return cell;
  }
  const value = document.createElement('div');
  value.className = 'metric-value';
  value.textContent = fmt(Math.round(placement.value));
  const comparison = document.createElement('div');
  comparison.className = 'metric-comparison-copy';
  // Same direction as the bar below it and the headline counts above: worse on
  // the left, better on the right. Reading the text in one order and the
  // picture in the other made the two look like different claims.
  comparison.textContent = `${fmt(placement.n_higher)} worse · ${fmt(placement.n_equal)} similar · ${fmt(placement.n_lower)} better`;
  const bar = document.createElement('div');
  bar.className = 'rank-stack rank-stack-small mt-2';
  renderRankStack(bar, placement);
  // No percentile line: the bar underneath already shows the position, and a
  // third stacked line of grey text made this the densest block on the page.
  bar.title = placement.empirical_percentile_range
    ? `More than ${placement.empirical_percentile_range[0].toFixed(0)}–${placement.empirical_percentile_range[1].toFixed(0)}% of ${fmt(placement.reference_size)} incompatible donors`
    : `${fmt(placement.reference_size)} donors compared — too few for a percentage`;
  cell.append(value, comparison, bar);
  return cell;
}

function renderMetricAgreement(result) {
  const box = $('metric-agreement');
  const placements = METRIC_ORDER.map((metric) => result.placements[`current:${metric}`]).filter(Boolean);
  if (!placements.length) {
    box.className = 'd-none';
    return;
  }
  const shares = placements.map((placement) => placement.n_lower / placement.reference_size);
  const spread = Math.max(...shares) - Math.min(...shares);
  box.className = `metric-agreement ${spread >= 0.25 ? 'metric-agreement-warning' : 'metric-agreement-neutral'}`;
  box.textContent = spread >= 0.25
    ? 'Measures disagree — read the pattern, not one figure'
    : 'Measures agree';
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

$('btn-clear').addEventListener('click', () => {
  clearTimeout(state.parseTimer);
  state.parseTimer = null;
  state.parseGeneration += 1;
  $('paste-box').value = '';
  $('preview').classList.add('d-none');
  $('role-row').classList.add('d-none');
  $('problems').innerHTML = '';
  $('spec-count').textContent = '0 specificities';
  state.rows = [];
  state.roles = null;
  state.valid = false;
  invalidateResults();
  updateAssessButton();
});

$('context-detail-link').addEventListener('click', () => {
  const panel = $('detail-provenance');
  panel.open = true;
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});

$('drawer-input').addEventListener('shown.bs.offcanvas', () => $('paste-box').focus());

// The four explanation panels share one drawer. Whichever trigger opened it
// decides which panel is shown and what the header says.
document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-panel-target]');
  if (!trigger) return;
  showInfoPanel(trigger.dataset.panelTarget);
});

function showInfoPanel(name) {
  const panels = document.querySelectorAll('#drawer-info-body .info-panel');
  let title = '';
  panels.forEach((panel) => {
    const match = panel.dataset.panel === name;
    panel.classList.toggle('d-none', !match);
    if (match) title = panel.dataset.panelTitle;
  });
  if (title) $('drawer-info-title').textContent = title;
  $('drawer-info-body').scrollTop = 0;
}

$('btn-assess').addEventListener('click', assess);
$('donor-hla').addEventListener('input', () => {
  invalidateResults();
  updateAssessButton();
});
$('recip-hla').addEventListener('input', invalidateResults);

let previousRecipientBg = $('bg').value;
$('bg').addEventListener('change', () => {
  if ($('donor-bg').value === previousRecipientBg) $('donor-bg').value = $('bg').value;
  previousRecipientBg = $('bg').value;
  invalidateResults();
  showAssessmentError('');
  updateAssessButton();
});

['donor-bg', 'dp-mode', 'threshold'].forEach((id) => {
  $(id).addEventListener('change', () => {
    invalidateResults();
    showAssessmentError('');
    updateAssessButton();
  });
});

$('paste-box').addEventListener('input', () => {
  clearTimeout(state.parseTimer);
  state.parseGeneration += 1;
  state.valid = false;
  invalidateResults();
  updateAssessButton();
  if (!$('paste-box').value.trim()) {
    $('preview').classList.add('d-none');
    $('role-row').classList.add('d-none');
    $('problems').innerHTML = '';
    $('spec-count').textContent = '0 specificities';
    state.rows = [];
    state.roles = null;
    return;
  }
  state.parseTimer = setTimeout(() => {
    state.parseTimer = null;
    state.roles = null;
    parsePaste(false);
  }, 350);
});

/* The inputs live in a left drawer, so the results always own the full width
 * and there is no collapsed/expanded layout to keep in sync. This only refreshes
 * the strip that opens the drawer, so the settings behind it stay visible
 * without being read twice. */
/* Icon per fact rather than a word, so the row stays scannable at a glance.
 * The value keeps its text -- an icon alone would make "A" and "3" ambiguous --
 * and every chip carries both a title (hover) and an aria-label, because title
 * is not announced reliably by screen readers and does nothing on touch. */
const CHIP_ICONS = {
  recipient: ['bi-person-fill', 'Recipient blood group'],
  donor: ['bi-heart-pulse-fill', 'Donor blood group'],
  antibodies: ['bi-record-circle', 'Antibody specificities in the profile'],
  threshold: ['bi-funnel-fill', 'MFI cut-off: antibodies at or above this strength are counted'],
  cohort: ['bi-people-fill', 'Donors compared against'],
  incompatible: ['bi-shield-exclamation', 'Of those, donors this patient has antibodies against'],
  dp: ['bi-diagram-3-fill', 'How HLA-DP antibodies were handled'],
};

function updateInputSummary(result) {
  const facts = $('input-summary-facts');
  facts.innerHTML = '';
  const specs = state.rows.filter((row) => row.recognised && row.current !== null).length;
  const provenance = result?.meta?.provenance;
  const summary = result?.basis_summaries?.current;

  // Left of the divider: what was asked. Right: what it was measured against.
  // The cohort figure is the FULL cohort, not the incompatible subset -- that
  // subset excludes compatible donors, and a reader not told so assumes the
  // denominator is everything the patient could be offered.
  const asked = [
    ['recipient', $('bg').value, `Recipient blood group ${$('bg').value}`],
    ['donor', $('donor-bg').value, `Donor blood group ${$('donor-bg').value}`],
    ['antibodies', String(specs), `${specs} antibod${specs === 1 ? 'y' : 'ies'} in the profile`],
    ['threshold', fmt(Number($('threshold').value)), `Counting antibodies at MFI ${fmt(Number($('threshold').value))} or above`],
  ];
  const against = provenance
    ? [
      ['cohort', fmt(provenance.cohort_size), `Compared against ${fmt(provenance.cohort_size)} donors`],
      ['incompatible', fmt(summary?.reference_size ?? 0),
        `${fmt(summary?.reference_size ?? 0)} of them carry antibody this patient reacts to`],
      ['dp', null, `HLA-DP: ${describeDp(provenance)}`],
    ]
    : [];

  const append = (parts, muted) => parts.forEach(([key, value, description]) => {
    const [icon, fallback] = CHIP_ICONS[key];
    const chip = document.createElement('span');
    chip.className = `context-chip${muted ? ' context-chip-muted' : ''}`;
    chip.title = description || fallback;

    const glyph = document.createElement('i');
    glyph.className = `bi ${icon}`;
    glyph.setAttribute('aria-hidden', 'true');
    chip.appendChild(glyph);

    if (value !== null) {
      const strong = document.createElement('b');
      strong.textContent = value;
      chip.appendChild(strong);
    } else {
      // the DP chip has no number of its own, so it keeps its wording
      const tag = document.createElement('span');
      tag.className = 'context-chip-label';
      tag.textContent = describeDp(provenance);
      chip.appendChild(tag);
    }

    // title is not announced reliably; this is what a screen reader reads
    const sr = document.createElement('span');
    sr.className = 'visually-hidden';
    sr.textContent = description || fallback;
    chip.appendChild(sr);

    facts.appendChild(chip);
  });

  append(asked, false);
  if (against.length) {
    const divider = document.createElement('span');
    divider.className = 'context-divider';
    divider.textContent = 'vs';
    facts.appendChild(divider);
    append(against, true);
  }
}

function invalidateResults() {
  state.assessmentGeneration += 1;
  updateInputSummary(null);
  $('assess-label').textContent = 'Assess offer';
  $('btn-assess').setAttribute('aria-busy', 'false');
  $('results').classList.add('d-none');
  $('placeholder').classList.remove('d-none');
  document.querySelectorAll('.detail-panel[open]').forEach((panel) => {
    if (panel.id !== 'detail-measures') panel.open = false;
  });
}


// ---------------------------------------------------------------------------
// test profiles
// ---------------------------------------------------------------------------
/* Manual testing means retyping a profile, a donor type and four settings for
 * every check. These fixtures load a whole state from the URL instead:
 *
 *     /offer/?profile=1          numbered, as listed below
 *     /offer/?profile=worst-case named alias for the same thing
 *
 * Each one is chosen to land on a *different branch* of the interpretation
 * layer, so the set covers the states that are otherwise awkward to reach --
 * a compatible donor, suppressed percentiles, a DP-restricted cohort. The
 * counts in the comments were taken from the live donor set and will drift if
 * the data is replaced; they are orientation, not assertions.
 *
 * This is a client-side convenience only: no endpoint, no server state, and
 * nothing here changes what /offer/placement computes. To withdraw it, delete
 * this section -- there is no route to unregister.
 */
const TEST_PROFILES = {
  1: {
    alias: 'average',
    label: 'Average offer — three antibodies, one hits',
    bg: 'A',
    donorBg: 'A',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B44 DR15 DR7',
    donorHla: 'A1 A2 B8 B44 DR4 DR15',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nA1\t9000\t6000\nB7\t12000\t12000\nDR4\t7000\t4000',
  },
  2: {
    alias: 'worst-case',
    label: 'Worst case — every antibody hits the donor',
    bg: 'A',
    donorBg: 'A',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B44 DR15 DR7',
    donorHla: 'A1 A2 B7 B44 DR4 DR15',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nA1\t9000\t6000\nB7\t12000\t12000\nDR4\t7000\t4000',
  },
  3: {
    alias: 'compatible',
    label: 'Compatible — no antibody hits, nothing to rank',
    bg: 'A',
    donorBg: 'A',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B44 DR15 DR7',
    donorHla: 'A2 A3 B8 B44 DR7 DR15',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nA1\t9000\t6000\nB7\t12000\t12000\nDR4\t7000\t4000',
  },
  4: {
    alias: 'single-antibody',
    label: 'Single antibody — ties dominate, ranking cannot discriminate',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B44 DR15 DR7',
    donorHla: 'A1 A2 B7 B44 DR4 DR15',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nB7\t15000\t12000',
  },
  5: {
    alias: 'dp',
    label: 'DP antibodies — cohort restricted to DP-typed donors',
    bg: 'A',
    donorBg: 'A',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B44 DR15 DR7',
    donorHla: 'A1 A2 B7 B44 DR4 DR15 DPB1 DPB3',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nB7\t11000\t9000\nDPB1\t6000\t5000',
  },
  6: {
    alias: 'small-cohort',
    label: 'AB recipient — reference below the floor, percentiles suppressed',
    bg: 'AB',
    donorBg: 'AB',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B44 DR15 DR7',
    donorHla: 'A1 A2 B7 B44 DR4 DR15',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nA1\t9000\t6000\nB7\t12000\t12000',
  },
  7: {
    alias: 'no-peak',
    label: 'Current MFI only — peak basis unavailable',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: '',
    donorHla: 'A1 A2 B7 B44 DR4 DR15',
    paste: 'Specificity\tCurrent MFI\nA1\t6000\nB7\t12000\nDR4\t4000',
  },
  8: {
    alias: 'broad-sensitisation',
    label: 'Broadly sensitised - 12 antibodies hit this donor',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B18 DR3 DR7',
    // donors_v3 id 249: carries 19 antigens, 12 of them DSA against this
    // profile. Leaves 28 of 4,620 donors compatible (0.6%) -- a cRF ~99%
    // patient, where almost every offer is incompatible.
    // B703/DR51/DR53 dropped from the real donor type: the mismatch view
    // accepts B/DR broads only, and none of them is an antibody target here,
    // so the burden numbers are unchanged.
    donorHla: 'A3 A11 B7 B12 B44 BW4 BW6 CW5 CW7 DR2 DR15 DR4 DQ1 DQ6 DQ3 DQ7',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nA3\t12000\t9000\nA11\t9000\t7000\nB7\t18000\t15000\n'
      + 'B12\t14000\t11000\nB44\t16000\t13000\nCW7\t8000\t6000\nDR4\t13000\t10000\n'
      + 'DR15\t11000\t8000\nDQ1\t7000\t5000\nDQ3\t11000\t9000\nDQ6\t9000\t7000\nDQ7\t15000\t12000',
  },
  9: {
    alias: 'worst-possible',
    label: 'Every antigen a target - 26 antibodies hit this donor',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    // No recipient B/DR here: the mismatch view accepts B/DR broads only and
    // would reject this donor's splits (B5102, DR1403, ...), several of which
    // ARE antibody targets. Dropping them would change the result, so the
    // joint view is omitted instead and the 26-DSA donor is kept whole.
    recipHla: '',
    // donors_v3 id 6242, the densest donor in the set: 30 antigens, and every
    // one of its 26 plausible antibody targets is a DSA. Also exercises the DP
    // pathway -- the DP specificities restrict the cohort to DP-typed donors.
    donorHla: 'A2 A203 A210 A9 A24 A2403 B5 B51 B5102 B5103 B22 B55 BW4 BW6 CW2 CW3 CW9 '
      + 'DR2 DR15 DR6 DR14 DR1403 DR1404 DR51 DR52 DQ1 DQ5 DQ6 DPB1 DPB3',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nA2\t21000\t18000\nA203\t14000\t11000\n'
      + 'A210\t13000\t10000\nA9\t17000\t14000\nA24\t19000\t16000\nA2403\t12000\t9000\n'
      + 'B5\t20000\t17000\nB51\t22000\t19000\nB5102\t15000\t12000\nB5103\t14000\t11000\n'
      + 'B22\t18000\t15000\nB55\t16000\t13000\nCW2\t11000\t8000\nCW3\t13000\t10000\n'
      + 'CW9\t10000\t7000\nDR2\t19000\t16000\nDR15\t21000\t18000\nDR6\t15000\t12000\n'
      + 'DR14\t17000\t14000\nDR1403\t12000\t9000\nDR1404\t11000\t8000\nDQ1\t18000\t15000\n'
      + 'DQ5\t14000\t11000\nDQ6\t16000\t13000\nDPB1\t13000\t10000\nDPB3\t12000\t9000',
  },
  10: {
    alias: 'dominant-antibody',
    label: 'One dominant antibody among weak ones - measures disagree',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B18 DR3 DR7',
    // The metric-disagreement case: cumulative puts this at the 100th centile
    // while median puts it at the 0th -- a spread of 1.00, the maximum
    // possible. That is what the "measures disagree" warning exists for.
    donorHla: 'A1 A3 B7 B44 BW4 BW6 CW7 DR4 DR15 DQ1 DQ3',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nB7\t24000\t22000\nA1\t3000\t2500\n'
      + 'A3\t3000\t2500\nDR4\t3000\t2500\nDR15\t3000\t2500\nDQ1\t3000\t2500\nCW7\t3000\t2500',
  },
  11: {
    alias: 'above-average',
    label: 'Above average - only a mid-strength antibody hits',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B18 DR3 DR7',
    // donors_v3 id 53: one DSA (DR7 at 13,000). 1,398 of 4,620 donors are
    // better (30%), 3,147 worse -- the "better than most" band.
    donorHla: 'A2 A3 B7 B17 B57 BW4 BW6 CW6 CW7 DR4 DR7 DQ3 DQ8 DQ9',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nB8\t18000\t16000\nDR3\t17000\t15000\n'
      + 'B18\t16000\t14000\nDR7\t15000\t13000\nB35\t14000\t12000\nDR11\t13000\t11000\n'
      + 'A1\t5000\t3000\nDQ7\t5000\t3000\nA11\t4500\t2500\nCW4\t4500\t2500\nDQ2\t4500\t2500',
  },
  12: {
    alias: 'very-good',
    label: 'Very good - as easy as an incompatible offer gets',
    bg: 'O',
    donorBg: 'O',
    threshold: 2000,
    dpMode: 'auto',
    recipHla: 'B8 B18 DR3 DR7',
    // donors_v3 id 85: one DSA, and it is the weakest antibody in the profile
    // (CW7 at 2,500). Only the 105 compatible donors are better -- 2.3% of the
    // cohort -- and 4,372 are worse.
    //
    // The patient is deliberately more sensitised than profile 11. With a
    // lighter profile the compatible donors alone are 13% of the cohort, which
    // no incompatible offer can beat, so the top band is unreachable.
    donorHla: 'A9 A24 A19 A30 B7 BW6 CW7 DR2 DR15 DQ1 DQ6',
    paste: 'Specificity\tPeak MFI\tCurrent MFI\nB8\t18000\t16000\nA1\t17000\t15000\n'
      + 'DR3\t17000\t15000\nB18\t16000\t14000\nA3\t16000\t14000\nDR7\t16000\t14000\n'
      + 'B35\t15000\t13000\nDR11\t15000\t13000\nB44\t14000\t12000\nDR4\t14000\t12000\n'
      + 'DQ2\t13000\t11000\nCW7\t4500\t2500',
  },
};

function findTestProfile(token) {
  const key = String(token).trim().toLowerCase();
  if (TEST_PROFILES[key]) return TEST_PROFILES[key];
  return Object.values(TEST_PROFILES).find((profile) => profile.alias === key) || null;
}

/* Fills the form, then runs the assessment. Waits for the debounced parse to
 * settle rather than racing it: the assess button stays disabled until the
 * paste has been recognised server-side, so clicking earlier does nothing. */
async function loadTestProfile(token) {
  const profile = findTestProfile(token);
  if (!profile) {
    // clear any banner from a previous load, or the page claims to be showing
    // a fixture it did not load
    $('test-profile-banner')?.remove();
    const known = Object.entries(TEST_PROFILES)
      .map(([number, entry]) => `${number} (${entry.alias})`)
      .join(', ');
    showAssessmentError(`Unknown test profile "${token}". Available: ${known}.`);
    return;
  }

  $('bg').value = profile.bg;
  $('donor-bg').value = profile.donorBg;
  $('threshold').value = profile.threshold;
  $('dp-mode').value = profile.dpMode;
  $('recip-hla').value = profile.recipHla;
  $('donor-hla').value = profile.donorHla;
  $('paste-box').value = profile.paste;

  announceTestProfile(profile);

  state.roles = null;
  await parsePaste(false);
  updateAssessButton();
  if (!$('btn-assess').disabled) assess();
}

/* The banner matters: a screenshot of fixture data must never be mistaken for
 * a real assessment. */
function announceTestProfile(profile) {
  let banner = $('test-profile-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'test-profile-banner';
    banner.className = 'test-profile-banner';
    $('provenance').insertAdjacentElement('beforebegin', banner);
  }
  banner.textContent = `Test profile ${profile.alias} — ${profile.label}. Fixture data, not a real patient.`;
}

const requestedProfile = new URLSearchParams(window.location.search).get('profile');
if (requestedProfile) loadTestProfile(requestedProfile);
