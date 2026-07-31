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
};

const $ = (id) => document.getElementById(id);
const fmt = (n) => (n === null || n === undefined ? '—' : n.toLocaleString());

// ---------------------------------------------------------------------------
// parsing
// ---------------------------------------------------------------------------

async function parsePaste(useRoles) {
  const text = $('paste-box').value;
  if (!text.trim()) return;
  state.lastText = text;

  const body = { text };
  if (useRoles && state.roles) body.roles = state.roles;

  const response = await fetch('/offer/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const result = await response.json();

  state.rows = result.rows;
  state.roles = result.roles;
  state.columns = result.columns;

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
      spec.innerHTML = `<s>${row.raw_spec}</s>`;
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
          new RegExp(`\\b${problem.token}\\b`), suggestion);
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
  return {
    bg: $('bg').value,
    specs: state.rows
      .filter((r) => r.recognised && r.current !== null)
      .map((r) => ({ spec: r.spec, current: r.current, peak: r.peak })),
    dp_mode: $('dp-mode').value,
    threshold: parseFloat($('threshold').value) || 2000,
  };
}

function updateAssessButton() {
  const hasSpecs = state.rows.some((r) => r.recognised && r.current !== null);
  const hasDonor = $('donor-hla').value.trim().length > 0;
  $('btn-assess').disabled = !(hasSpecs && hasDonor);
}

async function assess() {
  const donorText = $('donor-hla').value.trim();
  const donorResponse = await fetch('/offer/parse-donor', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: donorText }),
  });
  const donorResult = await donorResponse.json();

  if (donorResult.problems.length) {
    $('donor-parse').innerHTML = donorResult.problems
      .map((p) => `<span class="text-danger">${p.message}</span>`)
      .join('<br>');
    return;
  }
  $('donor-parse').textContent = `Recognised: ${donorResult.antigens.join(', ')}`;

  const payload = { ...profilePayload(), donor_hla: donorResult.antigens };
  const recipHla = $('recip-hla').value.trim();
  if (recipHla) payload.recip_hla = recipHla;

  const response = await fetch('/offer/placement', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json();
    $('problems').innerHTML = `<div class="problem error">${error.detail}</div>`;
    return;
  }

  render(await response.json());
}

// ---------------------------------------------------------------------------
// rendering results
// ---------------------------------------------------------------------------

function render(result) {
  $('placeholder').classList.add('d-none');
  $('results').classList.remove('d-none');

  renderProvenance(result.meta);

  $('hl-dsa').textContent = result.dsa_count;
  $('hl-ref').textContent = fmt(result.reference_size);
  $('hl-same').textContent = fmt(result.identical_dsa_set_count);
  $('hl-specs').innerHTML = result.dsa_specs.length
    ? result.dsa_specs.map((s) => `<span class="badge bg-danger-subtle text-danger-emphasis">${s}</span>`).join(' ')
    : '<span class="text-success">No DSA against this donor</span>';

  renderMetrics(result);
  renderJoint(result.joint);
}

function renderJoint(joint) {
  const card = $('joint-card');
  if (!joint || !joint.cells.length) {
    card.classList.add('d-none');
    return;
  }
  card.classList.remove('d-none');

  const bands = [...new Set(joint.cells.map((c) => c.burden_band))].sort();
  const body = $('joint-body');
  body.innerHTML = '';

  bands.forEach((band) => {
    const tr = document.createElement('tr');
    const label = document.createElement('td');
    label.textContent = band === 1 ? `Band ${band} (lowest)` : `Band ${band}`;
    tr.appendChild(label);

    [1, 2, 3, 4].forEach((level) => {
      const cell = joint.cells.find((c) => c.burden_band === band && c.mismatch_level === level);
      const td = document.createElement('td');
      td.textContent = cell ? cell.count.toLocaleString() : '·';
      if (band === joint.offered_burden_band && level === joint.offered_mismatch_level) {
        td.className = 'offered';
        td.title = 'The offered donor sits here';
      }
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  // the number neither axis answers alone
  $('joint-summary').innerHTML =
    `<strong>${fmt(joint.n_better_on_both)}</strong> donors are better on both axes `
    + `(lower burden <em>and</em> a better mismatch level); `
    + `<strong>${fmt(joint.n_worse_on_both)}</strong> are worse on both. `
    + `<span class="text-muted">Banded on ${joint.metric} (${joint.basis}).</span>`;
}

function renderProvenance(meta) {
  const strip = $('provenance');
  strip.classList.remove('d-none');
  const provenance = meta.provenance;

  $('prov-set').textContent = provenance.donor_set.replace('donors_', 'Set ');
  $('prov-dp').textContent = provenance.dp_mode_applied
    + (provenance.dp_mode_requested === 'auto' ? ' (auto)' : '');
  $('prov-cohort').textContent = provenance.dp_typed_only
    ? `${fmt(provenance.cohort_size)} of ${fmt(provenance.set_size_before_dp)}`
    : fmt(provenance.cohort_size);
  $('prov-abo').textContent = provenance.abo_rule;
  $('prov-tier').textContent = provenance.tier || '—';
  $('prov-threshold').textContent = `MFI ≥ ${fmt(meta.threshold)}`;

  const notes = $('prov-notes');
  notes.innerHTML = '';
  (meta.notes || []).forEach((note) => {
    const div = document.createElement('div');
    const critical = note.includes('cannot be corroborated')
      || note.includes('too small')
      || note.includes('discarded')
      || note.includes('cannot discriminate');
    div.className = `prov-note${critical ? ' critical' : ''}`;
    div.textContent = note;
    notes.appendChild(div);
  });
}

function renderMetrics(result) {
  const container = $('metric-panels');
  container.innerHTML = '';

  METRIC_ORDER.forEach((metric) => {
    const panel = document.createElement('div');
    panel.className = 'metric-panel';

    const header = document.createElement('div');
    header.className = 'metric-panel-header';
    header.innerHTML = `<span>${metric}</span>`
      + `<span class="metric-definition">${METRIC_DEFINITIONS[metric]}</span>`;
    panel.appendChild(header);

    // current and peak in the same panel: their divergence is the signal
    result.bases_available.forEach((basis) => {
      const placement = result.placements[`${basis}:${metric}`];
      if (placement) panel.appendChild(basisRow(basis, placement, metric));
    });

    if (result.peak_unavailable_reason && result.bases_available.length === 1) {
      const note = document.createElement('div');
      note.className = 'basis-row text-muted small fst-italic';
      note.textContent = result.peak_unavailable_reason;
      panel.appendChild(note);
    }

    container.appendChild(panel);
  });
}

function basisRow(basis, placement, metric) {
  const row = document.createElement('div');
  row.className = 'basis-row';

  const tag = document.createElement('span');
  tag.className = 'basis-tag';
  tag.textContent = basis;

  const value = document.createElement('span');
  value.className = 'basis-value';
  value.textContent = fmt(Math.round(placement.value));

  // the count first and largest: it survives translation into a clinical
  // conversation, and it moves with the ABO denominator where the percentile
  // barely does
  const counts = document.createElement('div');
  counts.innerHTML =
    `<div class="count-primary">${fmt(placement.n_lower)} lower</div>`
    + `<div class="count-detail">${fmt(placement.n_equal)} equal · `
    + `${fmt(placement.n_higher)} higher · of ${fmt(placement.reference_size)}</div>`;

  const bar = document.createElement('div');
  bar.className = 'dist-bar';
  if (placement.reference_size) {
    const lowerFrac = placement.n_lower / placement.reference_size;
    const tieFrac = placement.n_equal / placement.reference_size;
    const tie = document.createElement('div');
    tie.className = 'dist-tie';
    tie.style.left = `${lowerFrac * 100}%`;
    tie.style.width = `${Math.max(tieFrac * 100, 0.5)}%`;
    bar.appendChild(tie);
    const marker = document.createElement('div');
    marker.className = 'dist-marker';
    marker.style.left = `${lowerFrac * 100}%`;
    bar.appendChild(marker);
  }

  const percentile = document.createElement('div');
  percentile.className = 'percentile-secondary';
  if (placement.percentile === null || placement.percentile === undefined) {
    percentile.innerHTML = `<span class="percentile-suppressed">too few to characterise</span>`;
  } else {
    // metric identity travels with the number: a screenshot of a percentile must
    // be unambiguous about which ordering produced it
    const ci = placement.percentile_ci
      ? ` <span class="text-muted">(${placement.percentile_ci[0].toFixed(0)}–${placement.percentile_ci[1].toFixed(0)})</span>`
      : '';
    percentile.innerHTML = `${placement.percentile.toFixed(1)}th${ci}`
      + `<div class="count-detail">${metric} · ${basis}</div>`;
  }

  row.append(tag, value, counts, bar, percentile);
  return row;
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------

$('btn-parse').addEventListener('click', () => {
  state.roles = null; // re-detect on an explicit preview
  parsePaste(false);
});

$('btn-clear').addEventListener('click', () => {
  $('paste-box').value = '';
  $('preview').classList.add('d-none');
  $('role-row').classList.add('d-none');
  $('problems').innerHTML = '';
  $('spec-count').textContent = '0 specificities';
  state.rows = [];
  state.roles = null;
  updateAssessButton();
});

$('btn-assess').addEventListener('click', assess);
$('donor-hla').addEventListener('input', updateAssessButton);

// re-assess on toggle change: these alter the reference set, not the display
['bg', 'dp-mode', 'threshold'].forEach((id) => {
  $(id).addEventListener('change', () => {
    if (!$('results').classList.contains('d-none')) assess();
  });
});

// paste straight into a preview -- the common path
$('paste-box').addEventListener('paste', () => {
  setTimeout(() => {
    state.roles = null;
    parsePaste(false);
  }, 10);
});
