$(document).ready(function () {
  recalculate();
});

var toggleOnIcon = "bi-toggle2-on";
var toggleOffIcon = "bi-toggle2-off";

// recalculate the cRF, Mb, and AvD
var recalculate = () => {
  var antigenList = getSelectedAntigens();
  calculate(antigenList);
};

//watch all the antigen checkboxes for changes
var AntigenCheckBoxes = $(".antigen-checkbox");
AntigenCheckBoxes.change(recalculate);
var getSelectedAntigens = () => {
  return AntigenCheckBoxes.filter(":checked")
    .map(function () {
      return this.value;
    })
    .get();
};

var calculate = (antigenList) => {
  var bg = $("input[name='abo']:checked").val();
  var dp = $("#id_dp-toggle i small").html() == "A" ? 0 : 1;
  var recip_hla = $(".recip-hla-select")
    .map(function () {
      if (this.value) return this.value;
    })
    .get();
  var specs = antigenList.join(",");
  $.get(`/calc/?bg=${bg}&specs=${specs}&recip_hla=${recip_hla}&donor_set=${dp}`, function (data) {
    $("#crf-text").html((data.results.crf * 100).toFixed(2) + "%");
    $("#avd-text").html(data.results.available);
    $("#id_dp-toggle").attr("title", `Total donors: ${data.total}`);
    $("#mp-text").html(data.results.matchability);
    $("#fm-text").html(data.results.favourable);
  }).fail(function (xhr, status, error) {
    console.error(xhr.responseText);
  });
};

// toggle all antigens by locus
var LocusNames = $(".crf-locus-name");

LocusNames.click(function () {
  var locus = this.id.split("-")[1];
  toggleAntigensByLocus(locus);
});

var toggleAntigensByLocus = (locus) => {
  var antigenCheckboxes = $(".antigen-" + locus);
  var targetCheckedState = !antigenCheckboxes.first().prop("checked");
  antigenCheckboxes.prop("checked", targetCheckedState);
  recalculate();
};

// blood group selection
$("input[name='abo']").change(recalculate);

// toggle donors with/without DP types
$("#id_dp-toggle").click(function () {
  var toggleIcon = $(this).find("i");
  toggleIcon.toggleClass(`${toggleOnIcon} ${toggleOffIcon}`);
  toggleIcon.find("small").html(toggleIcon.hasClass(toggleOnIcon) ? "A" : "D");
  $(".toggle-hide").toggleClass("d-none");
  recalculate();
});

// recipient type change
$(".recip-hla-select").change(recalculate);
