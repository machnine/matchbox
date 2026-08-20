"""Static contracts for the offer-assessment interpretation layer.

These guard the *interpretation* the page offers, not its wording for its own
sake. Where a string is asserted it is because losing it would let the page
mislead: a direction of travel, a tie count, a staleness guard, or a caveat
that must not be silently dropped.
"""

import re
from pathlib import Path

HTML = Path("web/offer.html").read_text(encoding="utf-8")
SCRIPT = Path("static/offer.js").read_text(encoding="utf-8")
STYLE = Path("static/offer.css").read_text(encoding="utf-8")


def test_primary_visual_names_ranking_direction_and_ties():
    assert "Less load" in HTML
    assert "More load" in HTML
    assert ">easier<" in HTML
    assert ">harder<" in HTML
    assert 'id="summary-equal"' in HTML
    assert "empirical_percentile_range" in SCRIPT


def test_bars_run_worse_on_the_left_to_better_on_the_right():
    """Requested after review: moving rightwards should mean a better offer.

    Five things encode this one direction -- segment order, marker position,
    brace order, the count labels and the axis captions. Flipping any subset
    leaves the marker pointing at the wrong band, so they are asserted together.
    """
    stack = SCRIPT[SCRIPT.index("function renderRankStack") :]
    stack = stack[: stack.index("function offerToneClass")]
    assert stack.index("['higher'") < stack.index("['equal'") < stack.index("['lower'")
    # the marker measures from the left, which is now the high-load end
    assert "placement.n_higher + placement.n_equal / 2" in stack


def test_marker_sits_in_the_middle_of_the_tie_band():
    """Donors in the tie band score identically, so the offer has no rank
    within it. Anchoring the marker to the band's edge implied it was the
    lightest of the tied group -- a position the data does not support."""
    stack = SCRIPT[SCRIPT.index("function renderRankStack") :]
    stack = stack[: stack.index("function offerToneClass")]
    assert "(placement.n_higher + placement.n_equal / 2) / total" in stack
    # not the bare edge, which is what it used to be
    assert "total ? placement.n_higher / total : 0" not in stack

    labels = SCRIPT[SCRIPT.index("function renderRankLabels") :]
    assert "[placement.n_higher, placement.n_equal, placement.n_lower]" in labels

    braces = SCRIPT[SCRIPT.index("function renderBraces") :]
    braces = braces[: braces.index("function renderFacts")]
    assert braces.index("n_incompatible") < braces.index("n_compatible)")

    # captions and count labels in the markup follow the same order
    assert HTML.index("More load") < HTML.index("Less load")
    assert HTML.index(">Worse<") < HTML.index(">Similar<") < HTML.index(">Better<")


def test_peak_is_shown_before_current_everywhere():
    """Peak is the historic high-water mark, so left-to-right reads down from
    the worst the antibody has been to where it stands today."""
    metrics = SCRIPT[SCRIPT.index("function renderMetrics") :]
    metrics = metrics[: metrics.index("function metricBasisCell")]
    assert metrics.index("metricBasisCell('Peak'") < metrics.index("metricBasisCell('Current'")

    # the ingestion preview: header order and cell order must agree
    assert HTML.index('<th class="text-end">Peak</th>') < HTML.index('<th class="text-end">Current</th>')
    assert "tr.append(spec, peak, current);" in SCRIPT

    # the example paste is the shape users copy, and the role dropdown offers
    # the columns in the same order
    placeholder = HTML[HTML.index('id="paste-box"') : HTML.index("</textarea>")]
    assert placeholder.index("Peak MFI") < placeholder.index("Current MFI")
    roles = SCRIPT[SCRIPT.index("const ROLE_LABELS") :]
    roles = roles[: roles.index("};")]
    assert roles.index("peak_mfi") < roles.index("current_mfi")


def test_fixture_pastes_keep_each_value_with_its_own_column():
    """Flipping the headers without flipping the values would relabel every
    peak as a current, which the parser accepts and scores wrongly."""
    block = SCRIPT[SCRIPT.index("const TEST_PROFILES") : SCRIPT.index("function findTestProfile")]
    # longer fixtures are written as several concatenated literals, so join the
    # fragments of each paste back together before parsing the rows
    for raw in re.findall(r"paste: ((?:'[^']*'\s*\+?\s*)+),", block):
        paste = "".join(re.findall(r"'([^']*)'", raw))
        rows = [row for row in paste.split("\\n") if row]
        header = rows[0].split("\\t")
        if "Peak MFI" not in header:
            continue  # the deliberate current-only fixture
        peak_at, current_at = header.index("Peak MFI"), header.index("Current MFI")
        assert peak_at < current_at, header
        for row in rows[1:]:
            cells = row.split("\\t")
            assert len(cells) == len(header), (header, row)
            # peak is a high-water mark: it can never sit below current
            assert float(cells[peak_at]) >= float(cells[current_at]), row


def test_compatible_offer_is_presented_as_not_rankable():
    assert "compatible_no_dsa" in SCRIPT
    assert "No antibody against this donor" in SCRIPT
    assert "status.textContent = 'Compatible'" in SCRIPT


def test_current_and_peak_use_basis_specific_summaries():
    assert "result.basis_summaries.current" in SCRIPT
    assert "result.basis_summaries.peak" in SCRIPT
    assert "Compare each basis only with its own denominator" not in SCRIPT  # API note, not invented client-side


def test_offer_inputs_include_donor_blood_group_and_staleness_guards():
    assert 'id="donor-bg"' in HTML
    assert '<option value="O" selected>O</option>' in HTML
    assert "assessmentGeneration" in SCRIPT
    assert "parseGeneration" in SCRIPT
    assert "state.parseGeneration += 1" in SCRIPT
    assert "donor_bg: $('donor-bg').value" in SCRIPT


def test_profile_edits_auto_preview_without_a_redundant_button():
    assert 'id="btn-parse"' not in HTML
    assert "state.parseTimer = setTimeout" in SCRIPT
    assert "parsePaste(false);" in SCRIPT


def test_zero_threshold_is_not_replaced_by_the_default():
    assert "Number.isFinite(threshold) ? threshold : 2000" in SCRIPT
    assert "parseFloat($('threshold').value) || 2000" not in SCRIPT


def test_visualisation_has_distinct_lower_tie_and_higher_segments():
    for class_name in ("rank-segment-lower", "rank-segment-equal", "rank-segment-higher"):
        assert f".{class_name}" in STYLE
    assert "['lower', placement.n_lower," in SCRIPT
    assert "['equal', placement.n_equal," in SCRIPT
    assert "['higher', placement.n_higher," in SCRIPT


def test_population_segments_carry_no_verdict_colour():
    """Length means "how many donors"; it must not also mean good or bad.

    Colouring "donors better than this offer" green made a *worse* offer show a
    longer green bar, because a long bar reads as "more of a good thing". The
    two channels fought and length won. Segments are now neutral: only the
    offer marker is coloured.
    """
    green, red = "#65a979", "#dc6b75"
    for class_name in (".rank-segment-lower", ".rank-segment-higher"):
        block = STYLE[STYLE.index(class_name) : STYLE.index(class_name) + 90]
        assert green not in block
        assert red not in block


def test_only_the_offer_marker_carries_the_verdict_colour():
    assert ".offer-marker-low" in STYLE
    assert ".offer-marker-mid" in STYLE
    assert ".offer-marker-high" in STYLE
    assert "offerToneClass" in SCRIPT
    # the legend key must match the mark it names
    assert ".legend-swatch.offer-marker-high" in STYLE


def test_badge_and_marker_cannot_disagree():
    """Both read from one function, so the page cannot show a red badge over a
    green mark."""
    assert "status.classList.add(badgeTone[offerToneClass(placement)])" in SCRIPT
    assert "lowerShare >= 0.75 ? 'text-bg-danger'" not in SCRIPT


def test_an_all_tie_distribution_is_not_reported_as_a_good_offer():
    """With one specificity every donor scores the same, so n_lower is 0 for a
    reason that is not "this offer is easy"."""
    assert "if (placement.n_equal === placement.reference_size) return 'This comparison cannot separate the donors'" in SCRIPT
    assert "if (placement.n_equal === placement.reference_size) return 'offer-marker-mid'" in SCRIPT


def test_offer_marker_stays_inside_the_track():
    """An offer at either extreme still shows a whole marker."""
    assert "Math.min(99, Math.max(1, position * 100))" in SCRIPT


def test_primary_count_labels_follow_the_bar_segment_proportions():
    assert 'id="summary-counts"' in HTML
    assert ".rank-counts" in STYLE
    assert "container.style.gridTemplateColumns = counts" in SCRIPT
    assert "${count}fr" in SCRIPT


def test_count_labels_cannot_wrap_into_a_tower():
    """A proportional column can be a few pixels wide.

    With wrapping allowed, a squeezed label became a vertical stack of single
    characters that stretched the verdict card to several times its height.
    """
    assert "white-space: nowrap" in STYLE
    assert "text-overflow: ellipsis" in STYLE
    # a hidden group must keep its grid slot, or following labels shift columns
    assert "visibility: hidden" in STYLE
    assert "display: none" not in STYLE.split(".rank-count-group.is-empty")[1][:80]


def test_verdict_labels_read_as_a_judgement_in_a_consistent_direction():
    """"Better" must mean less antibody load everywhere it appears."""
    assert ">Better<" in HTML
    assert ">Similar<" in HTML
    assert ">Worse<" in HTML
    assert "'carry less antibody load than this offer'" in SCRIPT
    assert "'carry more antibody load than this offer'" in SCRIPT
    assert "This offer carries less antibody load than" in SCRIPT


def test_server_messages_are_inserted_as_text_not_markup():
    assert "error.textContent = message" in SCRIPT
    assert "struck.textContent = row.raw_spec" in SCRIPT
    assert "error.detail}</div>" not in SCRIPT


# --------------------------------------------------------------------------
# progressive disclosure
# --------------------------------------------------------------------------


def test_secondary_detail_is_collapsed_not_deleted():
    """Verbosity was the complaint; losing the findings would be the wrong fix."""
    for panel in ("detail-measures", "detail-provenance", "joint-card"):
        assert f'id="{panel}"' in HTML
    # top-level panels only; the joint card nests one more for its breakdown
    assert HTML.count('<details class="detail-panel') == 3
    # exactly one panel opens by default, and it is the one holding data rather
    # than prose -- the results column read as unfinished with all three closed
    opened = [tag for tag in re.findall(r"<details[^>]*>", HTML) if " open" in tag]
    assert len(opened) == 1, opened
    assert "detail-measures" in opened[0]
    assert "metric-panels" in HTML
    assert "joint-body" in HTML


def test_verdict_card_carries_no_paragraph():
    """Prose in a results panel is something to read; the card should be seen.

    The 40-word sentence that used to sit here restated numbers displayed
    directly beneath it.
    """
    assert 'id="summary-copy"' not in HTML
    assert 'id="summary-denominator"' not in HTML
    assert "plainVerdict" not in SCRIPT
    assert "cohortVerdict" not in SCRIPT
    # replaced by two figures and a brace row
    assert 'id="summary-facts"' in HTML
    assert 'id="bar-braces"' in HTML
    assert "function renderFacts(cohort)" in SCRIPT


def test_compatible_share_is_drawn_not_asserted():
    """The brace's width IS the proportion, so the number and the picture
    cannot drift apart."""
    assert "function renderBraces(cohort)" in SCRIPT
    assert "cohort.n_compatible / cohort.cohort_size" in SCRIPT
    assert ".bar-brace" in STYLE


def test_glossary_lives_in_an_offcanvas_not_the_results_column():
    assert 'id="drawer-info"' in HTML
    assert 'data-panel="meaning"' in HTML
    assert "What this does not tell you" in HTML
    assert "Why counts, not a rank" in HTML
    assert "renderWhatThisMeans" in SCRIPT
    # the glossary must not be inline in the results column
    assert 'id="detail-what"' not in HTML


def test_every_explanation_is_reachable_from_an_icon():
    """One drawer holds every explanation; the trigger chooses the panel, so
    each panel must have both a definition and something that opens it."""
    for panel in ("meaning", "measures", "joint", "method"):
        assert f'data-panel="{panel}"' in HTML
        assert f'data-panel-target="{panel}"' in HTML
    # a single right-hand drawer, not one per explanation
    assert HTML.count("offcanvas offcanvas-end") == 1
    assert HTML.count('class="info-panel') == 4
    # every trigger points at that one drawer
    assert HTML.count('data-panel-target=') == HTML.count('data-bs-target="#drawer-info"')
    # and the swap is wired up
    assert "function showInfoPanel(name)" in SCRIPT


def test_caveats_are_chipped_on_the_card_and_expanded_in_a_drawer():
    """Presence is visible; the prose is not in the results column."""
    assert 'id="caveat-chip"' in HTML
    assert 'id="caveat-count"' in HTML
    assert 'id="drawer-notes"' in HTML
    assert "chip.classList.toggle('d-none', flagged === 0)" in SCRIPT


def test_comparison_group_is_stated_before_any_number_is_read():
    """Provenance moved into a panel, but what is being compared must stay
    visible. One row now: the settings and the population they were measured
    against used to be two bars repeating three of the same facts.
    """
    assert 'id="input-summary-facts"' in HTML
    assert 'id="provenance"' in HTML
    assert HTML.count('class="context-bar"') == 1
    assert "function updateInputSummary(result)" in SCRIPT
    assert "cohort', fmt(provenance.cohort_size)" in SCRIPT
    assert "'incompatible', fmt(summary?.reference_size ?? 0)" in SCRIPT


def test_caveats_are_flagged_on_the_collapsed_provenance_panel():
    """A closed panel must still advertise that it contains warnings."""
    assert 'id="prov-flag-count"' in HTML
    assert "caveat" in SCRIPT
    assert "flag.classList.toggle('d-none', flagged === 0)" in SCRIPT


def test_page_copy_says_antibody_load_rather_than_burden():
    """'Burden' stays in the API; the page speaks to a mixed audience."""
    assert "antibody load" in HTML.lower()
    for phrase in ("Lower burden", "Higher burden", "burden group", "Observed burden group"):
        assert phrase not in HTML
    # the API vocabulary is still shown, so a screenshot maps onto the JSON
    assert "<code>cumulative</code>" in HTML


def test_metric_names_are_explained_not_just_capitalised():
    assert "METRIC_LABELS" in SCRIPT
    assert "Strongest single antibody" in SCRIPT
    assert "name.textContent = metric[0].toUpperCase()" not in SCRIPT


def test_detail_panels_reset_when_inputs_change():
    """A fresh assessment opens on the answer, not mid-scroll in a table."""
    assert "document.querySelectorAll('.detail-panel[open]')" in SCRIPT


def test_percentile_gloss_states_direction_of_travel():
    """A percentile measured from the low end reads backwards without a
    direction. Whatever label carries it must name which way is up."""
    assert "bottom ${" not in SCRIPT
    assert "of incompatible donors carry less" in SCRIPT


# --------------------------------------------------------------------------
# test profiles
# --------------------------------------------------------------------------


def test_test_profiles_are_client_side_only():
    """No endpoint backs the fixtures, so there is nothing to disable later.

    If this ever fails, a fixture has grown a server route and the "delete the
    section to withdraw it" promise in offer.js is no longer true.
    """
    api_source = Path("api/offer.py").read_text(encoding="utf-8")
    assert "profile=" not in api_source
    assert "TEST_PROFILES" not in api_source
    assert "TEST_PROFILES" in SCRIPT
    assert "new URLSearchParams(window.location.search).get('profile')" in SCRIPT


def test_every_test_profile_is_addressable_by_number_and_alias():
    import re

    entries = re.findall(r"\n  (\d+): \{\n    alias: '([a-z-]+)'", SCRIPT)
    numbers = [int(number) for number, _ in entries]
    aliases = [alias for _, alias in entries]
    assert numbers == list(range(1, len(numbers) + 1))  # contiguous from 1
    assert len(set(aliases)) == len(aliases)  # aliases unambiguous
    assert len(numbers) >= 6
    assert "findTestProfile" in SCRIPT


def test_test_profiles_cover_the_awkward_interpretation_branches():
    """The fixtures exist to reach states that are tedious to type by hand."""
    for alias in ("worst-case", "compatible", "single-antibody", "dp", "small-cohort", "no-peak"):
        assert f"alias: '{alias}'" in SCRIPT


def test_fixture_data_is_labelled_as_such():
    """A screenshot of fixture data must never pass for a real assessment."""
    assert "Fixture data, not a real patient" in SCRIPT
    assert ".test-profile-banner" in STYLE
    # and the banner must not survive a failed load
    assert "$('test-profile-banner')?.remove()" in SCRIPT


def test_unknown_profile_token_lists_the_valid_ones():
    assert 'Unknown test profile' in SCRIPT
    assert "Available: ${known}" in SCRIPT


# --------------------------------------------------------------------------
# cohort-wide denominator
# --------------------------------------------------------------------------


def test_primary_view_uses_the_whole_cohort_not_the_incompatible_subset():
    """Ranking inside the incompatible subset excludes every compatible donor,
    and those are the unambiguously better offers. For a single-DSA patient that
    hides ~73% of the cohort."""
    assert "result.cohort_placements?.current" in SCRIPT
    assert "renderCohortPrimary" in SCRIPT
    assert "no antibody" in SCRIPT  # the brace naming the compatible group


def test_context_bar_states_the_full_cohort_as_the_denominator():
    """The cohort chip must carry the FULL cohort size, not the incompatible
    subset: that subset excludes compatible donors, and a reader not told so
    assumes the denominator is everything the patient could be offered."""
    assert "['cohort', fmt(provenance.cohort_size)" in SCRIPT
    assert "['incompatible', fmt(summary?.reference_size ?? 0)" in SCRIPT


def test_status_row_does_not_repeat_itself():
    """Two bars had grown up separately and duplicated the cohort size, the MFI
    cut-off and the recipient blood group between them."""
    summary_fn = SCRIPT[SCRIPT.index("function updateInputSummary(result)") :]
    summary_fn = summary_fn[: summary_fn.index("\nfunction ")]
    # one chip per fact: each key appears once as a chip definition
    for fact in ("['recipient'", "['donor'", "['antibodies'", "['threshold'", "['cohort'"):
        assert summary_fn.count(fact) == 1, fact
    # and the second bar's own chip renderer is gone
    assert "context-chips" not in SCRIPT
    assert 'id="context-chips"' not in HTML


def test_incompatible_only_view_is_labelled_as_the_narrower_question():
    assert "Among incompatible donors" in HTML
    # the explanation itself lives in the drawer, not the panel header
    assert "These figures exclude every compatible donor" in HTML
    assert 'data-panel-target="measures"' in HTML


def test_headline_and_tone_read_from_one_band():
    """A blue badge over a "worse than most" headline is a contradiction; both
    must come from the same cut-offs."""
    assert "function cohortBand(cohort)" in SCRIPT
    assert "}[cohortBand(cohort)]" in SCRIPT
    # and "most" means more than half, not more than three quarters
    assert "if (share < 0.5) return 'lowish'" in SCRIPT
    assert "if (share > 0.5) return 'high'" in SCRIPT


def test_results_column_is_graphics_not_prose():
    """The complaint that drove this: explanatory text in the results column
    reads as clutter. Long sentences belong in a drawer."""
    import re

    body = HTML[HTML.index('<div id="results"') : HTML.index('<!-- ---', HTML.index('<div id="results"') + 200)]
    prose = [" ".join(m.split()) for m in re.findall(r">([^<>]{40,})<", body)]
    assert not prose, f"long prose left in the results column: {prose}"


def test_non_ranked_offers_clear_the_previous_visual():
    """The bar is hidden but its numbers stay in the DOM otherwise."""
    assert "$('summary-bar').innerHTML = ''" in SCRIPT
    assert "$('summary-facts').innerHTML = ''" in SCRIPT
    assert "$('bar-braces').innerHTML = ''" in SCRIPT


# --------------------------------------------------------------------------
# layout
# --------------------------------------------------------------------------


def test_page_is_not_capped_to_a_reading_column():
    """col-xxl-8 spent 666px of a 1920px screen on margin and left the primary
    bar at 35% of the viewport -- narrower than the margin beside it."""
    assert "col-xxl-8" not in HTML
    assert "offer-shell" in HTML
    assert ".offer-shell" in STYLE
    assert "max-width: 1800px" in STYLE


def test_inputs_live_in_a_drawer_so_the_results_own_the_page():
    """The form was a column that collapsed after assessing: two layout states
    kept in sync by hand across four elements. As a drawer it is shown or
    hidden by Bootstrap, and the results are always full width."""
    assert 'id="drawer-input"' in HTML
    assert 'id="input-rail"' not in HTML
    assert 'id="results-area"' in HTML
    # the paste box is inside the drawer, not the page body
    assert HTML.index('id="paste-box"') > HTML.index('id="drawer-input"')
    # the summary strip opens it
    assert 'data-bs-target="#drawer-input"' in HTML
    # and the hand-rolled state machine is gone
    for dead in ("collapseInputRail", "expandInputRail"):
        assert dead not in SCRIPT, dead
    # no .is-wide selectors remain; the results have no narrow variant now
    assert ".is-wide " not in STYLE
    assert "#results-area.is-wide" not in STYLE
    assert "is-wide" not in SCRIPT


def test_assessing_closes_the_input_drawer():
    """Otherwise the drawer covers the results it just produced."""
    assert "bootstrap.Offcanvas.getInstance($('drawer-input'))" in SCRIPT
    assert "drawer.hide();" in SCRIPT


def test_collapsed_summary_states_what_was_assessed():
    """A collapsed control must still say what it is hiding."""
    assert "$('input-summary-facts')" in SCRIPT
    assert "CHIP_ICONS" in SCRIPT
    assert "Counting antibodies at MFI" in SCRIPT
    assert "Compared against ${fmt(provenance.cohort_size)} donors" in SCRIPT


def test_icon_chips_keep_their_wording_available():
    """An icon alone is ambiguous. Every chip carries a title for hover and a
    visually-hidden label, because title is not announced reliably by screen
    readers and does nothing at all on touch."""
    for key in ("recipient", "donor", "antibodies", "threshold", "cohort", "incompatible", "dp"):
        assert f"{key}: ['bi-" in SCRIPT, key
    assert "chip.title = description || fallback" in SCRIPT
    assert "sr.className = 'visually-hidden'" in SCRIPT
    assert ".visually-hidden {" in STYLE
    # the glyph itself is decorative; the text beside it carries the meaning
    assert "glyph.setAttribute('aria-hidden', 'true')" in SCRIPT


def test_detail_panels_lay_out_as_a_grid():
    """Unconditional now: with the inputs in a drawer the results are always
    full width, so there is no narrow variant to gate these on."""
    assert ".detail-stack {" in STYLE
    assert "grid-template-columns: repeat(auto-fit" in STYLE


# --------------------------------------------------------------------------
# joint view
# --------------------------------------------------------------------------


def test_joint_card_leads_with_its_finding():
    """"Load x tissue match" named the axes but not the question. The question
    is whether the patient could do better on both counts at once, and that
    answer was a single number sitting under a 16-cell grid."""
    assert "Could this patient do better?" in HTML
    assert 'id="joint-headline"' in HTML
    assert "better on both antibody load and tissue match" in SCRIPT
    # the grid is now evidence behind the finding, not the first thing read
    assert 'id="joint-breakdown"' in HTML
    assert HTML.index('id="joint-headline"') < HTML.index('id="joint-breakdown"')


def test_joint_counts_account_for_every_reference_donor():
    """better + worse + trade-off must be the whole reference set, or the
    trade-off figure is silently wrong."""
    assert "const tradeoff = Math.max(0, total - better - worse);" in SCRIPT


def test_uk_specific_mismatch_levels_are_spelled_out():
    """Mismatch levels are an NHSBT scheme and mean nothing outside it."""
    assert "MISMATCH_LEVEL_DETAIL" in SCRIPT
    for detail in ("0 DR, 0-1 B mismatches", "1 DR, 0 B mismatches"):
        assert detail in SCRIPT, detail
    assert "UK (NHSBT)" in HTML
    assert "This is a UK-specific scheme" in HTML
    # the grid headers carry the mismatch counts, not bare L1-L4
    assert "0 DR 2 B, or 1 DR 1 B" in HTML


def test_thin_segments_get_leader_lines_not_bare_alignment():
    """At 4,372/143/105 the two thin segments are ~3% of the track, far too
    narrow to sit a label under. Alignment cannot carry the link there, so the
    label drifts to its segment and a drawn line closes the gap."""
    assert 'id="rank-leaders"' in HTML
    assert "function driftRankLabels(placement)" in SCRIPT
    assert "function drawLeaders(placed, width)" in SCRIPT
    assert ".rank-leader" in STYLE
    # the overlay must not intercept clicks meant for the card beneath it
    assert "pointer-events: none" in STYLE


def test_leader_lines_only_appear_when_a_segment_is_too_thin():
    """A balanced split reads correctly on alignment alone; drawing connectors
    there is furniture, not information."""
    assert "if (active.every((item) => item.segWidth >= item.width)) return;" in SCRIPT


def test_label_widths_are_measured_not_assumed():
    """The proportional grid stretches the big group to its full share and
    squeezes the thin ones, so neither the rendered box nor scrollWidth reports
    what a label actually needs -- both describe the space it was given."""
    assert "function naturalWidth(group)" in SCRIPT
    assert "width:max-content" in SCRIPT


def test_drift_falls_back_to_the_grid_when_labels_cannot_fit():
    """Drift needs somewhere to drift to. On a narrow bar the labels cannot be
    separated at any offset, and forcing it re-creates the overlap that drift
    exists to prevent."""
    assert "if (needed > width) return;" in SCRIPT
    # and a final check that bails rather than shipping a known-overlapping row
    assert "if (gap < 0) return;" in SCRIPT


def test_grid_floor_cannot_overflow_its_own_row():
    """Three 7rem floors demand 336px, which does not fit a 303px row: as a
    percentage against the column rather than the row, `min(7rem, 100%)` never
    capped it and the counts escaped the card."""
    assert "rowWidth / visible" in SCRIPT
    assert "min(7rem, 100%)" not in SCRIPT


def test_leaders_are_redrawn_when_the_bar_is_resized():
    """The whole layout is measured, so it is only correct until the box
    changes -- window resize, drawer opening, or a late font swap."""
    assert "ResizeObserver" in SCRIPT
    assert "driftRankLabels(lastPlacement)" in SCRIPT


def test_a_narrow_brace_does_not_truncate_its_own_caption():
    """A brace a few percent wide clipped "105 no antibody" to "105 n...".
    Above the bar there is nothing to collide with, so it overflows instead."""
    assert "is-narrow" in SCRIPT
    assert ".bar-brace.is-narrow" in STYLE


def test_braces_sit_above_the_bar_so_leaders_have_a_clear_band():
    """The gap below the track is where leader lines are drawn; the braces
    would otherwise be threaded through by them."""
    braces = HTML.index('id="bar-braces"')
    bar = HTML.index('id="summary-bar"')
    assert braces < bar


def test_each_headline_count_carries_its_share():
    """A count alone does not say how big it is: 143 is small against 4,620 and
    large against 200. The share is written beside it."""
    for name in ("higher", "equal", "lower"):
        assert f'id="summary-{name}-pct"' in HTML
    assert ".rank-count-pct" in STYLE
    assert "function renderCounts(shape)" in SCRIPT


def test_counts_and_shares_are_written_by_one_function():
    """The incompatible-only path and the whole-cohort path use different
    denominators, so writing the count and its share separately would let the
    two describe different populations."""
    assert SCRIPT.count("renderCounts(") >= 3  # definition + both render paths
    # neither path may still set the counts directly
    assert "$('summary-lower').textContent = fmt(" not in SCRIPT
    assert "$('summary-higher').textContent = fmt(" not in SCRIPT


def test_shares_never_round_into_a_contradiction():
    """99.98% rounding to "100%" beside a visibly non-empty group reads as a
    contradiction, as does "0%" over a count of 1."""
    assert "'<1%'" in SCRIPT
    assert "'>99%'" in SCRIPT
    assert "share > 99 && count < total" in SCRIPT


def test_a_cleared_assessment_drops_its_shares_too():
    """The visual is hidden but the numbers stay in the DOM; a later assessment
    must not inherit the previous offer's percentages."""
    clear = SCRIPT[SCRIPT.index("clear the previous offer's counts"):]
    clear = clear[: clear.index("$('summary-bar').innerHTML")]
    assert "-pct" in clear


def test_the_two_basis_columns_are_named_once_not_once_per_row():
    """PEAK and CURRENT appeared eight times across four rows, competing with
    the values they sat above."""
    assert "metric-head" in SCRIPT
    assert ".metric-head-label" in STYLE
    # the header is built once, outside the per-metric loop
    head = SCRIPT[SCRIPT.index("function renderMetrics"):SCRIPT.index("METRIC_ORDER.forEach")]
    assert "metric-head" in head


def test_stacked_layouts_still_name_their_columns():
    """Below 768px the two columns stack, so a single header above them names
    nothing and each cell has to say it again."""
    narrow = STYLE[STYLE.index("@media (max-width: 767.98px)"):]
    narrow = narrow[: narrow.index("@media (max-width: 420px)")]
    assert ".metric-row.metric-head" in narrow  # header hidden
    assert ".metric-basis-label" in narrow  # per-cell labels restored


def test_the_header_hide_outranks_the_narrow_row_display_rule():
    """`.metric-row { display: block }` in the 420px block comes later in the
    file, so hiding the header on `.metric-head` alone loses the cascade and
    the header reappears on phones."""
    assert ".metric-row.metric-head {" in STYLE


def test_restored_cell_labels_match_the_desktop_hide_specificity():
    """The desktop rule hides them with four classes; a three-class restore
    loses regardless of viewport, leaving stacked columns unnamed."""
    hide = ".metric-comparison .metric-head ~ .metric-row .metric-basis-label"
    assert STYLE.count(hide) == 2  # the desktop hide and the narrow restore


def test_every_metric_row_reserves_the_same_gutter():
    """The gutter once held an accent on the first row only, which inset that
    row's columns by three pixels. The accent is gone; the reserved space stays
    so every row still lines up with the header."""
    assert "border-left: 3px solid transparent;" in STYLE
    # no row may take a coloured edge back
    assert "border-left-color: #0d6efd;" not in STYLE


def test_metric_comparison_reads_the_same_direction_as_its_bar():
    """The bar runs worse-on-the-left to better-on-the-right; the sentence
    under it used to run the other way, so the two looked like different
    claims about the same donors."""
    assert "worse · ${fmt(placement.n_equal)} similar" in SCRIPT
    assert "n_higher)} worse" in SCRIPT
    assert "n_lower)} better`" in SCRIPT
    # the old order must be gone
    assert "n_lower)} better · " not in SCRIPT


def test_no_colour_marks_a_metric_row_as_special():
    """A tint and a blue edge on "Total load" read as a flag, but cumulative is
    simply first in METRIC_ORDER -- the colour encoded nothing."""
    assert "metric-row-primary" not in STYLE
    assert "metric-row-primary" not in SCRIPT
    assert "#f7fbff" not in STYLE


def test_the_verdict_card_has_no_status_coloured_edge():
    """A fixed blue border looked like a status accent while never varying with
    the status it sat beside."""
    card = STYLE[STYLE.index(".verdict-card {"):]
    card = card[: card.index("}")]
    assert "border-left" not in card
