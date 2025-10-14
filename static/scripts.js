document.addEventListener("DOMContentLoaded", async () => {
  // Fetch broad/split mapping
  try {
    const response = await fetch('/broad-split/');
    const data = await response.json();
    broadToSplits = data.broad_to_splits;
    splitToBroad = data.split_to_broad;
  } catch (error) {
    console.error('Failed to load broad/split mapping:', error);
  }
  
  // Initialize Bootstrap tooltips for ALL elements with title attribute
  // Wrapped in setTimeout to prevent Bootstrap's auto-initialization race condition
  setTimeout(() => {
    const allTooltipElements = document.querySelectorAll('[title], [data-bs-title]');
    
    allTooltipElements.forEach(function (element) {
      // Skip elements that have Bootstrap components (tabs, offcanvas, etc.)
      // These components don't play nicely with tooltips
      if (element.hasAttribute('data-bs-toggle')) {
        const toggleValue = element.getAttribute('data-bs-toggle');
        if (toggleValue === 'tab' || toggleValue === 'offcanvas') {
          return;
        }
      }
      
      // Dispose any existing tooltip first
      const existingTooltip = bootstrap.Tooltip.getInstance(element);
      if (existingTooltip) {
        existingTooltip.dispose();
      }
      
      const titleText = element.getAttribute('title') || element.getAttribute('data-bs-title');
      if (!titleText) return;
      
      // Remove title to prevent native tooltip
      element.removeAttribute('title');
      element.removeAttribute('data-bs-title');
      
      // Create Bootstrap tooltip
      new bootstrap.Tooltip(element, {
        title: titleText,
        trigger: 'hover focus',
        delay: { show: 500, hide: 100 },
        animation: true,
        html: false
      });
    });
  }, 100); // Small delay to let Bootstrap's auto-init finish first
  
  recalculate();
});

const toggleOnIcon = "bi-toggle2-on";
const toggleOffIcon = "bi-toggle2-off";

// Global variable to store the latest API response data
let currentApiData = null;

// Global variables for broad/split antigen mappings
let broadToSplits = {};
let splitToBroad = {};

// Global array to store accumulated flattened data
let storedData = [];

// Handle broad/split antigen relationships
const handleBroadSplitRelationship = (antigenName, isChecked) => {
  // Check if this is a broad antigen
  if (broadToSplits[antigenName]) {
    const splits = broadToSplits[antigenName];
    splits.forEach(split => {
      const splitCheckbox = document.getElementById(`id_${split}`);
      if (splitCheckbox) {
        splitCheckbox.checked = isChecked;
      }
    });
  }
  
  // Check if this is a split antigen
  if (splitToBroad[antigenName]) {
    const broad = splitToBroad[antigenName];
    const broadCheckbox = document.getElementById(`id_${broad}`);
    if (!broadCheckbox) return;
    
    const allSplits = broadToSplits[broad];
    
    if (isChecked) {
      // Split was checked - check if all splits are now checked
      const allSplitsChecked = allSplits.every(split => {
        const cb = document.getElementById(`id_${split}`);
        return cb && cb.checked;
      });
      if (allSplitsChecked) {
        broadCheckbox.checked = true;
      }
    } else {
      // Split was unchecked - uncheck the broad if it's checked
      if (broadCheckbox.checked) {
        broadCheckbox.checked = false;
      }
    }
  }
};

// recalculate the cRF, Mb, and AvD
const recalculate = () => {
  const antigenList = getSelectedAntigens();
  calculate(antigenList);
  displaySelectedAntigens(antigenList);
};

//watch all the antigen checkboxes for changes
const AntigenCheckBoxes = document.querySelectorAll(".antigen-checkbox");

AntigenCheckBoxes.forEach((checkbox) => {
  checkbox.addEventListener("change", function() {
    const antigenName = this.value; // e.g., "A19" or "A29"
    
    // Handle broad/split relationships FIRST
    handleBroadSplitRelationship(antigenName, this.checked);
    
    // Extract locus from checkbox class
    const locus = Array.from(this.classList)
      .filter((cls) => cls.startsWith("antigen-"))[0]
      .split("-")[1];
    
    // Reset this locus to "original" state and save current checkbox states
    const antigenCheckboxes = document.querySelectorAll(".antigen-" + locus);
    locusOriginalStates[locus] = Array.from(antigenCheckboxes).map(cb => cb.checked);
    locusStateTracker[locus] = "original";
    
    recalculate();
  });
});

// get the selected antigens
const getSelectedAntigens = () => {
  return Array.from(AntigenCheckBoxes)
    .filter((checkbox) => checkbox.checked)
    .map((checkbox) => {
      const locus = Array.from(checkbox.classList)
        .filter((cls) => cls.startsWith("antigen-"))[0]
        .split("-")[1];
      return { name: checkbox.value, locus: locus };
    });
};

// display the selected antigens
const displaySelectedAntigens = (antigenList) => {
  const specsDiv = document.getElementById("id-specificities");
  const inputArea = document.getElementById("antigen-input");
  specsDiv.innerHTML = "";
  const loci = [...new Set(antigenList.map((ag) => ag.locus))];

  // Create formatted display for specs div
  const locusSpansHTML = loci.map((locus) => {
    const locusAntigens = antigenList.filter((ag) => ag.locus === locus);
    const antigenNames = locusAntigens
      .map(
        (ag) =>
         
          `<span class="ps-1 spec-span" id="span-${ag.name}" ondblclick="toggleCheckbox('id_${ag.name}')">${ag.name}</span>`
      )
      .join(",<wbr>");
    return `<span class="crf-locus crf-bgcolor-${locus.toLowerCase()}">${antigenNames}</span>`;
  });

  // Update specs div
  specsDiv.innerHTML = locusSpansHTML.join(",<wbr>");
  
  // Update input textarea with plain text version
  const plainTextSpecs = antigenList.map(ag => ag.name).join(', ');
  inputArea.value = plainTextSpecs ? plainTextSpecs + ", " : "";
};

// calculate the cRF, Mb, and AvD based on the selected antigens
const calculate = (antigenList) => {
  const bg = document.querySelector("input[name='abo']:checked").value;
  const dpToggle = document.getElementById("id_dp-toggle");
  const dp = dpToggle.querySelector("i small").textContent === "A" ? 0 : 1;
  const recipHlaSelects = document.querySelectorAll(".recip-hla-select");
  const recip_hla = Array.from(recipHlaSelects)
    .map((select) => select.value)
    .filter((value) => value);
  const specs = antigenList.map((ag) => ag.name).join(",");

  fetch(`/calc/?bg=${bg}&specs=${specs}&recip_hla=${recip_hla}&donor_set=${dp}`)
    .then((response) => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then((data) => {
      // Store the API response data globally
      currentApiData = data;
      
      document.getElementById("crf-text").textContent = (data.results.crf * 100).toFixed(2) + "%";
      document.getElementById("avd-text").textContent = data.results.available;
      const dpToggle = document.getElementById("id_dp-toggle");
      
      // Update or create tooltip for the toggle button
      let dpTooltip = bootstrap.Tooltip.getInstance(dpToggle);
      const tooltipContent = `Total donors: ${data.total}`;
      
      if (dpTooltip) {
        // Update existing tooltip's title
        dpToggle.setAttribute('data-bs-original-title', tooltipContent);
        dpTooltip.setContent({ '.tooltip-inner': tooltipContent });
      } else {
        // Create new tooltip on first calculation (without data-bs-toggle attribute)
        dpTooltip = new bootstrap.Tooltip(dpToggle, {
          title: tooltipContent,
          trigger: 'hover focus',
          delay: { show: 500, hide: 100 },
          animation: true,
          html: false,
          placement: 'bottom'
        });
      }
      
      document.getElementById("mp-text").textContent = data.results.matchability;
      document.getElementById("fm-text").textContent = data.results.favourable;

      if (data.results.match_counts) {
        const mc = data.results.match_counts;
        const convRatio = data.total / 10000; // convert DP only donor calcs to 10k donor scale
        const m12a = Math.round(mc.m12a / convRatio) || 0;
        const m12b = Math.round(mc.m12b / convRatio) || 0;
        const m2b = Math.round(mc.m2b / convRatio) || 0;
        const m3a = Math.round(mc.m3a / convRatio) || 0;
        const m3b = Math.round(mc.m3b / convRatio) || 0;
        const m4a = Math.round(mc.m4a / convRatio) || 0;
        const m4b = Math.round(mc.m4b / convRatio) || 0;
        const total = m12a + m12b + m2b + m3a + m3b + m4a + m4b;        
        document.getElementById("m12a").textContent = m12a;
        document.getElementById("m2b").textContent = m2b;
        document.getElementById("m3a").textContent = m3a;
        document.getElementById("m3b").textContent = m3b;
        document.getElementById("m4a").textContent = m4a;
        document.getElementById("m4b").textContent = m4b;
        document.getElementById("total-donors").textContent = total;
      }
    })
    .catch((error) => {
      console.error(error);
    });
};

// Toggle all antigens by locus with 3-state cycle: original -> clear-all -> check-all -> original
const locusStateTracker = {};
const locusOriginalStates = {};

const LocusNames = document.querySelectorAll(".crf-locus-name");
LocusNames.forEach((locusName) => {
  locusName.addEventListener("click", function () {
    const locus = this.id.split("-")[1];
    toggleAntigensByLocus(locus);
  });
});

const toggleAntigensByLocus = (locus) => {
  const antigenCheckboxes = document.querySelectorAll(".antigen-" + locus);
  const currentState = locusStateTracker[locus] || "original";
  
  if (currentState === "original") {
    // Save current state and move to clear-all
    locusOriginalStates[locus] = Array.from(antigenCheckboxes).map(cb => cb.checked);
    antigenCheckboxes.forEach((checkbox) => (checkbox.checked = false));
    locusStateTracker[locus] = "clear-all";
  } else if (currentState === "clear-all") {
    // Move to check-all
    antigenCheckboxes.forEach((checkbox) => (checkbox.checked = true));
    locusStateTracker[locus] = "check-all";
  } else if (currentState === "check-all") {
    // Restore original state
    antigenCheckboxes.forEach((checkbox, index) => {
      checkbox.checked = locusOriginalStates[locus][index];
    });
    locusStateTracker[locus] = "original";
  }
  
  recalculate();
};

// blood group selection
const aboInputs = document.querySelectorAll("input[name='abo']");
aboInputs.forEach((aboInput) => {
  aboInput.addEventListener("change", recalculate);
});

// toggle donors with/without DP types
const dpToggle = document.getElementById("id_dp-toggle");
dpToggle.addEventListener("click", function () {
  const toggleIcon = this.querySelector("i");
  toggleIcon.classList.toggle(toggleOnIcon);
  toggleIcon.classList.toggle(toggleOffIcon);
  toggleIcon.querySelector("small").textContent = toggleIcon.classList.contains(toggleOnIcon) ? "A" : "D";
  document.querySelectorAll(".toggle-hide").forEach((el) => el.classList.toggle("d-none"));
  recalculate();
});

// recipient type change
const recipHlaSelects = document.querySelectorAll(".recip-hla-select");
recipHlaSelects.forEach((select) => {
  select.addEventListener("change", recalculate);
});

// copy specs
const button = document.getElementById("btn-copy-specs");
button.addEventListener("click", () => {
  const specsDiv = document.getElementById("id-specificities");
  const copyIcon = document.getElementById("id-copy-icon");
  const copyMsg = document.getElementById("id-copy-msg");
  navigator.clipboard
    .writeText(specsDiv.textContent)
    .then(() => {
      copyIcon.classList.remove("bi-copy");
      copyIcon.classList.add("bi-check2-all");
      copyMsg.classList.remove("d-none");
      setTimeout(() => {
        copyIcon.classList.add("bi-copy");
        copyIcon.classList.remove("bi-check2-all");
        copyMsg.classList.add("d-none");
      }, 1000);
    })
    .catch((err) => {
      console.error("Failed to copy: ", err);
    });
});

// function to toggle a checkbox given its id
const toggleCheckbox = (checkboxId) => {
  const checkbox = document.getElementById(checkboxId);
  const newState = !checkbox.checked;
  checkbox.checked = newState;
  
  // Handle broad/split relationships
  const antigenName = checkbox.value;
  handleBroadSplitRelationship(antigenName, newState);
  
  recalculate();
};

// Parse and process input antigens
const processInputAntigens = (inputText) => {
  // First clear all existing checkboxes
  document.querySelectorAll('.antigen-checkbox').forEach(checkbox => {
    checkbox.checked = false;
  });
  
  // Split on commas or spaces and clean up each antigen
  const inputAntigens = inputText
    .split(/[,\s]+/)
    .map(ag => {
      ag = ag.trim().toUpperCase();
      // Convert Cn/cn to CWn
      if (ag.match(/^C\d+$/i)) {
        ag = ag.replace(/^C(\d+)$/i, 'CW$1');
      }
      // Convert DPn/dpn to DPBn
      if (ag.match(/^DP\d+$/i)) {
        ag = ag.replace(/^DP(\d+)$/i, 'DPB$1');
      }
      return ag;
    })
    .filter(ag => ag.length > 0);
  
  // Track which antigens weren't found
  const notFound = [];
  
  // Process each antigen and apply broad/split logic
  inputAntigens.forEach(ag => {
    const checkbox = document.getElementById(`id_${ag}`);
    if (checkbox) {
      checkbox.checked = true;
      // Apply broad/split relationships for this antigen
      handleBroadSplitRelationship(ag, true);
    } else {
      notFound.push(ag);
    }
  });
  
  // Alert user of any antigens that weren't found
  if (notFound.length > 0) {
    alert(`Could not find matches for: ${notFound.join(', ')}`);
  }
  
  // Always recalculate, even if no antigens were found
  recalculate();
};

// Add event listener for the input box
document.getElementById('antigen-input').addEventListener('keypress', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault(); // Prevent newline in textarea
    processInputAntigens(event.target.value);
  }
});

// Log current API data to console
document.getElementById('btn-log-data').addEventListener('click', () => {
  if (currentApiData) {
    let removed = [];
    let added = [];
    
    // Only calculate differences if this is not the first entry
    if (storedData.length > 0) {
      const previousSpecs = storedData[storedData.length - 1].specs;
      const currentSpecs = currentApiData.specs;
      
      // Calculate removed and added specs
      removed = previousSpecs.filter(spec => !currentSpecs.includes(spec));
      added = currentSpecs.filter(spec => !previousSpecs.includes(spec));
    }
    
    // Create flattened data with only specified fields in the requested order
    const flattenedData = {
      crf: currentApiData.results.crf * 100,
      matchability: currentApiData.results.matchability,
      favourable: currentApiData.results.favourable,
      available: currentApiData.results.available,
      recip_hla: currentApiData.recip_hla,
      specs: currentApiData.specs,
      removed: removed,
      added: added
    };
    
    // Add current data to memory
    storedData.push(flattenedData);
    
    // Update profile count badge
    updateProfileCountBadge();
  } else {
    console.log('No API data available yet. Please wait for calculations to complete.');
  }
});

// Export stored data to TSV and copy to clipboard
document.getElementById('btn-export-csv').addEventListener('click', () => {
  if (storedData.length === 0) {
    console.log('No data stored yet. Please add some profiles first using the Add button.');
    // Visual feedback for no data
    const copyIcon = document.getElementById('export-copy-icon');
    const copyMsg = document.getElementById('export-copy-msg');
    const copyText = document.getElementById('export-copy-text');
    
    // Hide normal elements and show no data feedback
    copyText.classList.add('d-none');
    copyMsg.textContent = 'No data!';
    copyMsg.classList.remove('d-none');
    copyIcon.classList.remove('bi-clipboard');
    copyIcon.classList.add('bi-exclamation-circle');
    
    setTimeout(() => {
      // Restore normal state
      copyText.classList.remove('d-none');
      copyMsg.textContent = 'Copied!';
      copyMsg.classList.add('d-none');
      copyIcon.classList.add('bi-clipboard');
      copyIcon.classList.remove('bi-exclamation-circle');
    }, 2000);
    
    return;
  }
  
  // Convert array fields to comma-separated strings for TSV and handle null values
  const tsvData = storedData.map(row => ({
    'CRF (%)': row.crf || ' ',
    'Matchability': row.matchability || ' ',
    'Favourable': row.favourable || ' ',
    'Available': row.available || ' ',
    'Recipient HLA': row.recip_hla || ' ',
    'Unacceptable Specs': row.specs.length > 0 ? row.specs.join(',') : ' ',
    'Removed': row.removed.length > 0 ? row.removed.join(',') : ' ',
    'Added': row.added.length > 0 ? row.added.join(',') : ' '
  }));
  
  // Create TSV header and content with new descriptive headers
  const headers = ['CRF (%)', 'Matchability', 'Favourable', 'Available', 'Recipient HLA', 'Unacceptable Specs', 'Removed', 'Added'];
  const tsvContent = [
    headers.join('\t'), // Header row with tabs
    ...tsvData.map(row => headers.map(header => row[header]).join('\t')) // Data rows with tabs
  ].join('\n');
  
  // Copy to clipboard
  navigator.clipboard.writeText(tsvContent)
    .then(() => {
      // Visual feedback similar to copy specs button
      const copyIcon = document.getElementById('export-copy-icon');
      const copyMsg = document.getElementById('export-copy-msg');
      const copyText = document.getElementById('export-copy-text');
      
      // Hide normal elements and show feedback
      copyText.classList.add('d-none');
      copyIcon.classList.remove('bi-clipboard');
      copyIcon.classList.add('bi-check2-all');
      copyMsg.classList.remove('d-none');
      
      setTimeout(() => {
        // Restore normal state
        copyText.classList.remove('d-none');
        copyIcon.classList.add('bi-clipboard');
        copyIcon.classList.remove('bi-check2-all');
        copyMsg.classList.add('d-none');
      }, 2000);
      
      console.log('TSV data copied to clipboard!');
      console.log('TSV Content:\n' + tsvContent);
    })
    .catch((err) => {
      console.error('Failed to copy TSV to clipboard: ', err);
      // Show error feedback
      const copyIcon = document.getElementById('export-copy-icon');
      const copyMsg = document.getElementById('export-copy-msg');
      const copyText = document.getElementById('export-copy-text');
      
      // Hide normal elements and show error feedback
      copyText.classList.add('d-none');
      copyMsg.textContent = 'Error!';
      copyMsg.classList.remove('d-none');
      copyIcon.classList.remove('bi-clipboard');
      copyIcon.classList.add('bi-exclamation-triangle');
      
      setTimeout(() => {
        // Restore normal state
        copyText.classList.remove('d-none');
        copyMsg.textContent = 'Copied!';
        copyMsg.classList.add('d-none');
        copyIcon.classList.add('bi-clipboard');
        copyIcon.classList.remove('bi-exclamation-triangle');
      }, 2000);
      
      console.log('TSV Content:\n' + tsvContent);
    });
});

// Function to update the profile count badge
const updateProfileCountBadge = () => {
  const badge = document.getElementById('profile-count-badge');
  const count = storedData.length;
  
  if (count > 0) {
    badge.textContent = count;
    badge.classList.remove('d-none');
  } else {
    badge.classList.add('d-none');
  }
};
