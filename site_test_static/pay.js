/* 강사료 실수령 계산기 (test build only: pay.html).

   PayCalc.calc(rate, weeklyHours) compares one month of take-home pay under
   the two usual contracts for a Korean-language lecturer:
     - freelance (사업소득): 3.3% withheld (소득세 3% + 지방소득세 0.3%)
     - employee (근로소득): the worker's share of 국민연금, 건강보험,
       장기요양보험, 고용보험, and 소득세 approximated from the 간이세액표
       formula for a one-person household, plus 지방소득세 10%.
   Rates are the 2026 ones; update RATES each January. The pure part runs in
   node too, so tests/test_pay.py checks the math. */
(function (root) {
  "use strict";

  var RATES = {
    year: 2026,
    pension: 0.0475,          // 국민연금 9.5%, half paid by the worker
    pensionMin: 410000,       // 기준소득월액 하한·상한 (2026.7~2027.6)
    pensionMax: 6590000,
    health: 0.03595,          // 건강보험 7.19%, half
    care: 0.1314,             // 장기요양보험: 건강보험료 × 13.14%
    employment: 0.009,        // 고용보험 (실업급여) worker share
    freelanceTax: 0.03,       // 사업소득 원천징수
    localTax: 0.1             // 지방소득세 = 소득세 × 10%
  };
  var WEEKS_PER_MONTH = 52 / 12; // 4.33: an average month, not four weeks

  function floor10(won) { return Math.floor(won / 10) * 10; }

  // 근로소득공제
  function earnedDeduction(year) {
    var d = year <= 5e6 ? year * 0.7
      : year <= 15e6 ? 3.5e6 + (year - 5e6) * 0.4
      : year <= 45e6 ? 7.5e6 + (year - 15e6) * 0.15
      : year <= 100e6 ? 12e6 + (year - 45e6) * 0.05
      : 14.75e6 + (year - 100e6) * 0.02;
    return Math.min(d, 20e6);
  }

  // 특별소득공제 used by the 간이세액표 formula (공제대상가족 1명)
  function specialDeduction(year) {
    if (year <= 30e6) return 3.1e6 + year * 0.04;
    if (year <= 45e6) return 3.1e6 + year * 0.04 - (year - 30e6) * 0.05;
    if (year <= 70e6) return 3.1e6 + year * 0.015;
    if (year <= 120e6) return 3.1e6 + year * 0.005;
    return 3.1e6;
  }

  // 종합소득세 기본세율 (2023년 이후)
  function baseTax(base) {
    var brackets = [[14e6, 0.06, 0], [50e6, 0.15, 1.26e6], [88e6, 0.24, 5.76e6], [150e6, 0.35, 15.44e6],
                    [300e6, 0.38, 19.94e6], [500e6, 0.40, 25.94e6], [1e9, 0.42, 35.94e6], [Infinity, 0.45, 65.94e6]];
    for (var i = 0; i < brackets.length; i++) {
      if (base <= brackets[i][0]) return Math.max(0, base * brackets[i][1] - brackets[i][2]);
    }
    return 0;
  }

  // 근로소득세액공제 and its limit
  function earnedCredit(tax, year) {
    var credit = tax <= 1.3e6 ? tax * 0.55 : 715000 + (tax - 1.3e6) * 0.3;
    var limit = year <= 33e6 ? 740000
      : year <= 70e6 ? Math.max(660000, 740000 - (year - 33e6) * 0.008)
      : year <= 120e6 ? Math.max(500000, 660000 - (year - 70e6) * 0.5)
      : Math.max(200000, 500000 - (year - 120e6) * 0.5);
    return Math.min(credit, limit);
  }

  // Monthly 소득세 for a monthly wage, the way the 간이세액표 is built:
  // annualize, deduct, tax, credit, and divide by twelve.
  function monthlyIncomeTax(monthly, pensionMonthly) {
    var year = monthly * 12;
    var base = year - earnedDeduction(year) - 1.5e6 - pensionMonthly * 12 - specialDeduction(year);
    if (base <= 0) return 0;
    var tax = baseTax(base);
    return floor10(Math.max(0, tax - earnedCredit(tax, year)) / 12);
  }

  function calc(rate, weeklyHours) {
    rate = Math.max(0, Number(rate) || 0);
    weeklyHours = Math.max(0, Number(weeklyHours) || 0);
    var monthlyHours = weeklyHours * WEEKS_PER_MONTH;
    var gross = Math.round(rate * monthlyHours);

    var fIncome = floor10(gross * RATES.freelanceTax);
    var fLocal = floor10(fIncome * RATES.localTax);
    var freelance = {
      gross: gross,
      items: [["소득세 3%", fIncome], ["지방소득세 0.3%", fLocal]],
      net: gross - fIncome - fLocal
    };

    var pensionBase = Math.min(Math.max(gross, RATES.pensionMin), RATES.pensionMax);
    var pension = gross > 0 ? floor10(pensionBase * RATES.pension) : 0;
    var health = floor10(gross * RATES.health);
    var care = floor10(health * RATES.care);
    var employment = floor10(gross * RATES.employment);
    var income = monthlyIncomeTax(gross, pension);
    var local = floor10(income * RATES.localTax);
    var items = [["국민연금", pension], ["건강보험", health], ["장기요양보험", care],
                 ["고용보험", employment], ["소득세", income], ["지방소득세", local]];
    var employee = {
      gross: gross,
      items: items,
      net: gross - items.reduce(function (sum, it) { return sum + it[1]; }, 0)
    };

    return {
      monthlyHours: Math.round(monthlyHours * 10) / 10,
      gross: gross,
      freelance: freelance,
      employee: employee,
      // 월 60시간 미만이면 보통 4대보험(국민연금·건강보험·고용보험) 대상이 아니다.
      underSixty: monthlyHours > 0 && monthlyHours < 60
    };
  }

  var PayCalc = { calc: calc, RATES: RATES, monthlyIncomeTax: monthlyIncomeTax };
  if (typeof module !== "undefined" && module.exports) module.exports = PayCalc;
  root.PayCalc = PayCalc;

  // --- the page ------------------------------------------------------------
  if (typeof document === "undefined") return;
  var box = document.querySelector("[data-pay]");
  if (!box) return;

  var rateInput = box.querySelector("[data-rate]");
  var hoursInput = box.querySelector("[data-hours]");
  var params = new URLSearchParams(location.search);
  if (/^\d{4,6}$/.test(params.get("rate") || "")) rateInput.value = Number(params.get("rate")).toLocaleString("ko-KR");
  if (/^\d{1,2}(\.\d)?$/.test(params.get("hours") || "")) hoursInput.value = params.get("hours");
  var from = params.get("from");
  if (from) {
    var fromBox = box.querySelector("[data-from]");
    fromBox.querySelector("strong").textContent = from;
    fromBox.hidden = false;
  }

  function won(n) { return n.toLocaleString("ko-KR") + "원"; }
  function number(input) { return Number(String(input.value).replace(/[^\d.]/g, "")) || 0; }

  function fill(card, result) {
    card.querySelector("[data-net]").textContent = won(result.net);
    card.querySelector("[data-items]").innerHTML = "";
    result.items.forEach(function (it) {
      var row = document.createElement("div");
      var dt = document.createElement("dt");
      var dd = document.createElement("dd");
      dt.textContent = it[0];
      dd.textContent = "−" + won(it[1]);
      row.appendChild(dt);
      row.appendChild(dd);
      card.querySelector("[data-items]").appendChild(row);
    });
  }

  function update() {
    var r = calc(number(rateInput), number(hoursInput));
    var out = box.querySelector("[data-out]");
    out.hidden = r.gross <= 0;
    if (r.gross <= 0) return;
    box.querySelector("[data-gross]").textContent = won(r.gross);
    box.querySelector("[data-month-hours]").textContent = String(r.monthlyHours);
    fill(box.querySelector('[data-card="freelance"]'), r.freelance);
    fill(box.querySelector('[data-card="employee"]'), r.employee);
    box.querySelector("[data-under60]").hidden = !r.underSixty;
  }

  rateInput.addEventListener("input", function () {
    var n = number(rateInput);
    rateInput.value = n ? n.toLocaleString("ko-KR") : "";
    update();
  });
  hoursInput.addEventListener("input", update);
  update();
})(typeof window !== "undefined" ? window : globalThis);
