document.addEventListener("DOMContentLoaded", () => {
  recalculate();
});

const toggleOnIcon = "bi-toggle2-on";
const toggleOffIcon = "bi-toggle2-off";

// recalculate the cRF, Mb, and AvD
const recalculate = () => {
  const antigenList = getSelectedAntigens();
  calculate(antigenList);
  displaySelectedAntigens(antigenList);
};

//watch all the antigen checkboxes for changes
const AntigenCheckBoxes = document.querySelectorAll(".antigen-checkbox");

AntigenCheckBoxes.forEach((checkbox) => {
  checkbox.addEventListener("change", recalculate);
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
  specsDiv.innerHTML = "";
  const loci = [...new Set(antigenList.map((ag) => ag.locus))];

  const locusSpansHTML = loci.map((locus) => {
    const locusAntigens = antigenList.filter((ag) => ag.locus === locus);
    const antigenNames = locusAntigens.map((ag) => `<span class="ps-1">${ag.name}</span>`).join(",<wbr>");
    return `<span class="crf-locus crf-bgcolor-${locus.toLowerCase()}">${antigenNames}</span>`;
  });

  specsDiv.innerHTML = locusSpansHTML.join(",<wbr>");
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
      document.getElementById("crf-text").textContent = (data.results.crf * 100).toFixed(2) + "%";
      document.getElementById("avd-text").textContent = data.results.available;
      document.getElementById("id_dp-toggle").title = `Total donors: ${data.total}`;
      document.getElementById("mp-text").textContent = data.results.matchability;
      document.getElementById("fm-text").textContent = data.results.favourable;

      if (data.results.match_counts) {
        const mc = data.results.match_counts;
        const convRatio = data.total / 10000; // convert DP only donor calcs to 10k donor scale
        document.getElementById("m12a").textContent = Math.round(mc.m12a / convRatio);
        document.getElementById("m2b").textContent = Math.round(mc.m2b / convRatio);
        document.getElementById("m3a").textContent = Math.round(mc.m3a / convRatio);
        document.getElementById("m3b").textContent = Math.round(mc.m3b / convRatio);
        document.getElementById("m4a").textContent = Math.round(mc.m4a / convRatio);
        document.getElementById("m4b").textContent = Math.round(mc.m4b / convRatio);
      }
    })
    .catch((error) => {
      console.error(error);
    });
};

// toggle all antigens by locus
const LocusNames = document.querySelectorAll(".crf-locus-name");
LocusNames.forEach((locusName) => {
  locusName.addEventListener("click", function () {
    const locus = this.id.split("-")[1];
    toggleAntigensByLocus(locus);
  });
});

const toggleAntigensByLocus = (locus) => {
  const antigenCheckboxes = document.querySelectorAll(".antigen-" + locus);
  const targetCheckedState = !antigenCheckboxes[0].checked;
  antigenCheckboxes.forEach((checkbox) => (checkbox.checked = targetCheckedState));
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
