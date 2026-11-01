/* 강사료 실수령 계산기 (pay.html).

   PayCalc.calc(rate, hours, unit) compares one month of take-home pay under
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

  // hours are per week (unit "week", the default) or per month ("month").
  function calc(rate, hours, unit) {
    rate = Math.max(0, Number(rate) || 0);
    hours = Math.max(0, Number(hours) || 0);
    unit = unit === "month" ? "month" : "week";
    var monthlyHours = unit === "month" ? hours : hours * WEEKS_PER_MONTH;
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
    // One week is one month spread over its 4.33 weeks.
    var perWeek = function (won) { return floor10(won / WEEKS_PER_MONTH); };
    freelance.weekNet = perWeek(freelance.net);
    employee.weekNet = perWeek(employee.net);

    return {
      rate: rate,
      hours: hours,
      unit: unit,
      pensionBase: pensionBase,
      monthlyHours: Math.round(monthlyHours * 10) / 10,
      weeklyHours: Math.round(monthlyHours / WEEKS_PER_MONTH * 10) / 10,
      gross: gross,
      weekGross: perWeek(gross),
      freelance: freelance,
      employee: employee,
      // 월 60시간 미만이면 보통 4대보험(국민연금·건강보험·고용보험) 대상이 아니다.
      underSixty: monthlyHours > 0 && monthlyHours < 60
    };
  }

  var PayCalc = { calc: calc, RATES: RATES, WEEKS_PER_MONTH: WEEKS_PER_MONTH, monthlyIncomeTax: monthlyIncomeTax };
  if (typeof module !== "undefined" && module.exports) module.exports = PayCalc;
  root.PayCalc = PayCalc;

  // --- the page ------------------------------------------------------------
  if (typeof document === "undefined") return;
  // --- the job page's side box: 주당 시수 → 주급·월급 at this notice's fee --
  var mini = document.querySelector("[data-pay-mini]");
  if (mini) {
    var miniRate = Number(mini.getAttribute("data-rate"));
    var miniHours = mini.querySelector("[data-mini-hours]");
    var miniWon = function (n) { return n.toLocaleString("ko-KR") + "원"; };
    var miniUpdate = function () {
      var h = Number(String(miniHours.value).replace(/[^\d.]/g, "")) || 0;
      var r = calc(miniRate, h, "week");
      mini.querySelector("[data-mini-out]").hidden = r.gross <= 0;
      mini.querySelector("[data-mini-week]").textContent = miniWon(r.freelance.weekNet);
      mini.querySelector("[data-mini-week-gross]").textContent = miniWon(r.weekGross);
      mini.querySelector("[data-mini-month]").textContent = miniWon(r.freelance.net);
      mini.querySelector("[data-mini-month-gross]").textContent = miniWon(r.gross);
      var q = new URLSearchParams({ rate: String(miniRate) });
      if (h) q.set("hours", String(h));
      q.set("from", mini.getAttribute("data-from"));
      var more = mini.querySelector("[data-mini-more]");
      more.href = more.getAttribute("href").split("?")[0] + "?" + q.toString();
    };
    mini.querySelectorAll("[data-mini-rate]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        miniRate = Number(btn.getAttribute("data-mini-rate"));
        mini.querySelectorAll("[data-mini-rate]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        miniUpdate();
      });
    });
    miniHours.addEventListener("input", miniUpdate);
    miniUpdate();
  }

  var box = document.querySelector("[data-pay]");
  if (!box) return;

  var rateInput = box.querySelector("[data-rate]");
  var hoursInput = box.querySelector("[data-hours]");
  var unit = "week";
  var contract = "freelance";
  var params = new URLSearchParams(location.search);
  if (/^\d{4,6}$/.test(params.get("rate") || "")) rateInput.value = Number(params.get("rate")).toLocaleString("ko-KR");
  if (/^\d{1,2}(\.\d)?$/.test(params.get("hours") || "")) hoursInput.value = params.get("hours");
  var from = params.get("from");
  if (from) {
    var fromBox = box.querySelector("[data-from]");
    fromBox.querySelector("strong").textContent = from;
    fromBox.hidden = false;
  }

  var NOTES = {
    freelance: "3.3%는 미리 떼는 세금이에요. 5월 종합소득세 신고 때 정산해서 돌려받거나 더 낼 수 있어요. 건강보험료는 지역가입자로 따로 낼 수 있어요.",
    employee: "근로자가 내는 몫(절반)만 계산했어요. 소득세는 1인 가구 기준 어림값이라 실제와 조금 다를 수 있고, 연말정산으로 정산해요."
  };

  function won(n) { return n.toLocaleString("ko-KR") + "원"; }
  function num(n) { return (Math.round(n * 10) / 10).toLocaleString("ko-KR"); }
  function pct(r) { return (Math.round(r * 100000) / 1000) + "%"; }
  function number(input) { return Number(String(input.value).replace(/[^\d.]/g, "")) || 0; }
  function text(sel, value) { box.querySelector(sel).textContent = value; }

  // The folded detail: [label, expression, amount, kind] where kind is
  // "minus" for a deduction and "total" for a result line.
  function lines(r) {
    var g = won(r.gross);
    var grossExpr = r.unit === "month"
      ? won(r.rate) + " × " + num(r.hours) + "시간"
      : won(r.rate) + " × 주 " + num(r.hours) + "시간 × 4.33주";
    var out = [["한 달 세전", grossExpr, r.gross, "total"]];
    var c = r[contract];
    var amount = function (name) { return c.items.filter(function (it) { return it[0] === name; })[0][1]; };
    if (contract === "freelance") {
      out.push(["소득세", g + " × 3%", c.items[0][1], "minus"]);
      out.push(["지방소득세", "소득세 × 10%", c.items[1][1], "minus"]);
    } else {
      var pensionOf = r.pensionBase !== r.gross ? won(r.pensionBase) + "(상·하한 적용)" : g;
      out.push(["국민연금", pensionOf + " × " + pct(RATES.pension), amount("국민연금"), "minus"]);
      out.push(["건강보험", g + " × " + pct(RATES.health), amount("건강보험"), "minus"]);
      out.push(["장기요양보험", "건강보험료 × " + pct(RATES.care), amount("장기요양보험"), "minus"]);
      out.push(["고용보험", g + " × " + pct(RATES.employment), amount("고용보험"), "minus"]);
      out.push(["소득세", "간이세액표 어림 (1인 가구)", amount("소득세"), "minus"]);
      out.push(["지방소득세", "소득세 × 10%", amount("지방소득세"), "minus"]);
    }
    out.push(["한 달 실수령", "세전 − 뗀 돈", c.net, "total"]);
    out.push(["한 주 실수령", "한 달 실수령 ÷ 4.33주", c.weekNet, "total"]);
    return out;
  }

  function update() {
    var r = calc(number(rateInput), number(hoursInput), unit);
    var out = box.querySelector("[data-out]");
    out.hidden = r.gross <= 0;
    if (r.gross <= 0) return;
    var c = r[contract];
    text("[data-week-net]", won(c.weekNet));
    text("[data-week-gross]", won(r.weekGross));
    text("[data-month-net]", won(c.net));
    text("[data-month-gross]", won(r.gross));
    text("[data-basis]", "주 " + num(r.weeklyHours) + "시간 · 한 달 " + num(r.monthlyHours) + "시간 기준 (한 달 = 평균 4.33주)");
    box.querySelector("[data-under60]").hidden = !(contract === "employee" && r.underSixty);
    text("[data-contract-note]", NOTES[contract] + " 10원 미만은 버렸어요.");

    var list = box.querySelector("[data-formula]");
    list.innerHTML = "";
    lines(r).forEach(function (l) {
      var li = document.createElement("li");
      li.className = "pay-line " + l[3];
      var name = document.createElement("span");
      name.className = "pay-line-name";
      name.textContent = l[0];
      var expr = document.createElement("span");
      expr.className = "pay-line-expr";
      expr.textContent = l[1];
      var value = document.createElement("span");
      value.className = "pay-line-value";
      value.textContent = (l[3] === "minus" ? "−" : "") + won(l[2]);
      li.appendChild(name);
      li.appendChild(value);
      li.appendChild(expr);
      list.appendChild(li);
    });
  }

  function press(attr, btn) {
    box.querySelectorAll("[" + attr + "]").forEach(function (b) {
      b.setAttribute("aria-pressed", b === btn ? "true" : "false");
    });
  }

  // Switching the unit keeps the same amount of work: 주 12시간 becomes 한 달 52시간.
  box.querySelectorAll("[data-unit]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var next = btn.getAttribute("data-unit");
      if (next === unit) return;
      var h = number(hoursInput);
      if (h) {
        var converted = next === "month" ? h * WEEKS_PER_MONTH : h / WEEKS_PER_MONTH;
        hoursInput.value = String(Math.round(converted * 10) / 10);
      }
      unit = next;
      press("data-unit", btn);
      text("[data-hours-unit]", unit === "month" ? "시간/월" : "시간/주");
      update();
    });
  });

  box.querySelectorAll("[data-contract]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      contract = btn.getAttribute("data-contract");
      press("data-contract", btn);
      update();
    });
  });

  rateInput.addEventListener("input", function () {
    var n = number(rateInput);
    rateInput.value = n ? n.toLocaleString("ko-KR") : "";
    update();
  });
  hoursInput.addEventListener("input", update);
  update();
})(typeof window !== "undefined" ? window : globalThis);
