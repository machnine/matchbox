/* offer assessment page
 *
 * Two calls, mirroring the API: the profile builds the distributions, the donor
 * is placed against them. Counts are given at least equal weight to percentiles
 * throughout, and the metric identity travels with every number so a screenshot
 * of "3rd percentile" is never ambiguous about which ordering produced it.
 */

const METRIC_DEFINITIONS = {
  cumulative: 'sum of MFI across DSA',
  max: 'highest single specificity',
  mean: 'cumulative ÷ DSA count',
  median: 'median across DSA present',
};

const METRIC_ORDER = ['cumulative', 'max', 'mean', 'median'];

const ROLE_LABELS = {
  spec: 'Specificity',
  current_mfi: 'Current MFI',
  peak_mfi: 'Peak MFI',
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

    tr.append(spec, current, peak);
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
    showAssessmentError('This build can only compare a blood-group-identical offer. The offerable ABO policy mapping is not yet encoded.');
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
  $('donor-parse').textContent = `Recognised: ${donorResult.antigens.join(', ')}`;

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
  if (generation === state.assessmentGeneration) render(result);
  finishAssessment(generation);
}

// ---------------------------------------------------------------------------
// rendering results
// ---------------------------------------------------------------------------

function render(result) {
  $('placeholder').classList.add('d-none');
  $('results').classList.remove('d-none');

  renderProvenance(result.meta);
  const current = result.basis_summaries.current;
  $('hl-dsa').textContent = current.dsa_count;
  $('hl-ref').textContent = fmt(current.reference_size);
  $('hl-same').textContent = fmt(current.identical_dsa_set_count);
  renderDsaSpecs(current.dsa_specs);
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
    none.textContent = 'No current DSA against this donor at the selected threshold';
    container.appendChild(none);
    return;
  }
  specs.forEach((spec) => {
    const badge = document.createElement('span');
    badge.className = 'badge bg-danger-subtle text-danger-emphasis me-1';
    badge.textContent = spec;
    container.appendChild(badge);
  });
}

function renderPrimary(result, summary) {
  const status = $('summary-status');
  const visual = $('ranking-visual');
  const metricCard = $('metric-card');
  status.className = 'badge mb-2';

  if (summary.status !== 'ranked_incompatible') {
    visual.classList.add('d-none');
    metricCard.classList.toggle('d-none', Object.keys(result.placements).length === 0);
    $('summary-value').textContent = '—';
    if (summary.status === 'compatible_no_dsa') {
      status.classList.add('text-bg-success');
      status.textContent = 'Compatible at threshold';
      $('summary-title').textContent = 'Burden ranking is not applicable';
      $('summary-copy').textContent = 'No current DSA was detected against this donor. Compatible offers are not ranked inside the incompatible-donor reference.';
    } else if (summary.status === 'no_active_specificities') {
      status.classList.add('text-bg-warning');
      status.textContent = 'No active DSA profile';
      $('summary-title').textContent = 'Nothing remains to rank';
      $('summary-copy').textContent = 'No current specificities remain above the selected threshold after cohort policy was applied.';
    } else {
      status.classList.add('text-bg-warning');
      status.textContent = 'Reference unavailable';
      $('summary-title').textContent = 'No incompatible reference donors observed';
      $('summary-copy').textContent = 'The offer carries DSA, but this cohort contains no comparable incompatible donors.';
    }
    return;
  }

  visual.classList.remove('d-none');
  metricCard.classList.remove('d-none');
  const placement = result.placements['current:cumulative'];
  const lowerShare = placement.reference_size ? placement.n_lower / placement.reference_size : 0;
  status.classList.add(lowerShare <= 0.1 ? 'text-bg-success' : lowerShare >= 0.75 ? 'text-bg-danger' : 'text-bg-primary');
  status.textContent = 'Current cumulative burden';
  $('summary-title').textContent = positionTitle(placement);
  $('summary-copy').textContent = `${fmt(placement.n_lower)} incompatible donors had lower burden (potentially easier), ${fmt(placement.n_equal)} had the same burden, and ${fmt(placement.n_higher)} had higher burden (potentially harder).`;
  $('summary-value').textContent = fmt(Math.round(placement.value));
  $('summary-lower').textContent = fmt(placement.n_lower);
  $('summary-equal').textContent = fmt(placement.n_equal);
  $('summary-higher').textContent = fmt(placement.n_higher);
  renderRankStack($('summary-bar'), placement);
  renderRankLabels(placement);

  if (placement.empirical_percentile_range) {
    const [low, high] = placement.empirical_percentile_range;
    $('summary-denominator').textContent = `Among ${fmt(placement.reference_size)} current incompatible donors, ties place this offer across the ${low.toFixed(1)}–${high.toFixed(1)}% range from the low-burden end.`;
  } else {
    $('summary-denominator').textContent = `${fmt(placement.reference_size)} current incompatible donors observed; too few for a stable percentage, so use the counts above.`;
  }
}

function positionTitle(placement) {
  if (placement.n_lower === 0) return 'No lower-burden reference donor was observed';
  const share = placement.n_lower / placement.reference_size;
  if (share <= 0.1) return 'Near the lowest-burden end of the reference';
  if (share <= 0.25) return 'Toward the lower-burden end of the reference';
  if (share >= 0.75) return 'Toward the higher-burden end of the reference';
  return 'Within the middle of the reference burden range';
}

function renderRankStack(container, placement) {
  container.innerHTML = '';
  const groups = [
    ['lower', placement.n_lower],
    ['equal', placement.n_equal],
    ['higher', placement.n_higher],
  ];
  groups.forEach(([name, count]) => {
    const segment = document.createElement('span');
    segment.className = `rank-segment rank-segment-${name}`;
    segment.style.width = `${placement.reference_size ? (count / placement.reference_size) * 100 : 0}%`;
    segment.title = `${fmt(count)} donors with ${name === 'equal' ? 'the same' : name} burden`;
    container.appendChild(segment);
  });
  container.setAttribute('aria-label', `${fmt(placement.n_lower)} lower burden, ${fmt(placement.n_equal)} same burden, ${fmt(placement.n_higher)} higher burden`);
}

function renderRankLabels(placement) {
  const counts = [placement.n_lower, placement.n_equal, placement.n_higher];
  const container = $('summary-counts');
  container.style.gridTemplateColumns = counts.map((count) => `minmax(0, ${count}fr)`).join(' ');
  [...container.children].forEach((label, index) => {
    label.classList.toggle('is-empty', counts[index] === 0);
  });
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
    label.textContent = band === 1 ? 'Group 1 · lowest burden' : band === 4 ? 'Group 4 · highest burden' : `Group ${band}`;
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

  $('joint-summary').textContent = `This offer is in burden group ${joint.offered_burden_band} and mismatch level L${joint.offered_mismatch_level}. ${fmt(joint.n_better_on_both)} reference donors were strictly better on both axes; ${fmt(joint.n_worse_on_both)} were strictly worse on both. Ties and one-axis trade-offs are not included in those two counts.`;
}

function renderProvenance(meta) {
  const strip = $('provenance');
  strip.classList.remove('d-none');
  const provenance = meta.provenance;

  $('prov-set').textContent = provenance.donor_set.replace('donors_', 'Set ');
  if (provenance.dp_mode_requested === 'auto' && !provenance.patient_has_dp_specs) {
    $('prov-dp').textContent = 'full cohort (auto; no DP DSA)';
  } else if (provenance.dp_mode_applied === 'include') {
    $('prov-dp').textContent = `DP-typed only${provenance.dp_mode_requested === 'auto' ? ' (auto)' : ''}`;
  } else {
    $('prov-dp').textContent = `DP excluded${provenance.dp_mode_requested === 'auto' ? ' (auto)' : ''}`;
  }
  $('prov-cohort').textContent = provenance.dp_typed_only
    ? `${fmt(provenance.cohort_size)} of ${fmt(provenance.set_size_before_dp)}`
    : fmt(provenance.cohort_size);
  $('prov-abo').textContent = provenance.abo_rule;
  $('prov-tier').textContent = provenance.tier || '—';
  $('prov-threshold').textContent = `MFI ≥ ${fmt(meta.threshold)}`;
  const fingerprint = meta.data_provenance?.donor_database_sha256;
  $('prov-data').textContent = fingerprint ? fingerprint.slice(0, 10) : '—';
  $('prov-data').title = fingerprint || '';

  const notes = $('prov-notes');
  notes.innerHTML = '';
  (meta.notes || []).forEach((note) => {
    const div = document.createElement('div');
    const critical = note.includes('cannot be corroborated')
      || note.includes('too small')
      || note.includes('discarded')
      || note.includes('cannot discriminate');
    const warning = note.includes('restricted to blood-group-identical')
      || note.includes('not comparable')
      || note.includes('different incompatible reference populations');
    div.className = `prov-note${critical ? ' critical' : warning ? ' warning' : ''}`;
    div.textContent = note;
    notes.appendChild(div);
  });
}

function renderMetrics(result) {
  const container = $('metric-panels');
  container.innerHTML = '';

  renderMetricAgreement(result);
  METRIC_ORDER.forEach((metric) => {
    const row = document.createElement('div');
    row.className = `metric-row${metric === 'cumulative' ? ' metric-row-primary' : ''}`;

    const identity = document.createElement('div');
    identity.className = 'metric-identity';
    const name = document.createElement('strong');
    name.textContent = metric[0].toUpperCase() + metric.slice(1);
    const definition = document.createElement('span');
    definition.textContent = METRIC_DEFINITIONS[metric];
    identity.append(name, definition);
    row.appendChild(identity);
    row.appendChild(metricBasisCell('Current', result.placements[`current:${metric}`], result.basis_summaries.current));
    row.appendChild(metricBasisCell('Peak', result.placements[`peak:${metric}`], result.basis_summaries.peak, result.peak_unavailable_reason));
    container.appendChild(row);
  });
}

function metricBasisCell(label, placement, summary, unavailableReason) {
  const cell = document.createElement('div');
  cell.className = 'metric-basis-cell';
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
    unavailable.textContent = summary.status === 'compatible_no_dsa' ? 'No DSA; not ranked' : 'No placement available';
    cell.appendChild(unavailable);
    return cell;
  }
  const value = document.createElement('div');
  value.className = 'metric-value';
  value.textContent = fmt(Math.round(placement.value));
  const comparison = document.createElement('div');
  comparison.className = 'metric-comparison-copy';
  comparison.textContent = `${fmt(placement.n_lower)} lower · ${fmt(placement.n_equal)} same · ${fmt(placement.n_higher)} higher`;
  const range = document.createElement('div');
  range.className = 'metric-range';
  range.textContent = placement.empirical_percentile_range
    ? `${placement.empirical_percentile_range[0].toFixed(1)}–${placement.empirical_percentile_range[1].toFixed(1)}% from low end · n=${fmt(placement.reference_size)}`
    : `counts only · n=${fmt(placement.reference_size)}`;
  const bar = document.createElement('div');
  bar.className = 'rank-stack rank-stack-small mt-2';
  renderRankStack(bar, placement);
  cell.append(value, comparison, range, bar);
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
    ? 'The burden measures disagree materially about this offer’s position. Review the DSA pattern and do not quote a single rank as the answer.'
    : 'The burden measures place this offer in broadly similar parts of their observed distributions.';
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

function invalidateResults() {
  state.assessmentGeneration += 1;
  $('assess-label').textContent = 'Assess offer';
  $('btn-assess').setAttribute('aria-busy', 'false');
  $('results').classList.add('d-none');
  $('placeholder').classList.remove('d-none');
  $('provenance').classList.add('d-none');
}
