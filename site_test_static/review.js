/* 기관 평가 (test build only). Steps follow how people remember a workplace:
   which one → gut feeling → what stands out → areas → facts → last word.
   Only the institution and the gut feeling are required; the rest can be skipped.
   A draft stays in this browser until it is sent. */
(function () {
  "use strict";

  var root = document.querySelector("[data-review]");
  if (!root) return;
  var DATA = JSON.parse(document.getElementById("reviewData").textContent);
  var box = root.querySelector("[data-step-box]");
  var progress = root.querySelector("[data-progress]");
  var DRAFT_KEY = "review-draft-v1";
  var STEPS = [
    { key: "org", label: "기관" },
    { key: "overall", label: "첫인상" },
    { key: "memory", label: "기억" },
    { key: "areas", label: "영역 점수" },
    { key: "facts", label: "근무 조건" },
    { key: "closing", label: "마무리" }
  ];
  var AREA = {};
  DATA.areas.forEach(function (a) { AREA[a.key] = a; });

  function blank() {
    return { org: "", overall: 0, good: [], bad: [], areas: {}, items: {}, closing: {}, facts: {}, comment: "", step: 0 };
  }
  function loadDraft() {
    try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || "null"); } catch (e) { return null; }
  }
  function saveDraft() {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(state)); } catch (e) { /* private mode */ }
  }
  function dropDraft() {
    try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* private mode */ }
  }

  // A link from a job page names the institution; a draft for another one is set aside.
  var fromLink = new URLSearchParams(location.search).get("org") || "";
  var state = loadDraft() || blank();
  if (fromLink && state.org !== fromLink) {
    state = blank();
    state.org = fromLink;
    state.step = 1;
  }
  var current = null; // area row that keys 1-5 score
  var open = {};      // areas with their statements unfolded

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function button(cls, text, onClick) {
    var b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function has(list, key) { return list.indexOf(key) !== -1; }
  function without(list, key) { return list.filter(function (k) { return k !== key; }); }
  function count(obj) { return Object.keys(obj).length; }

  function go(step) {
    state.step = Math.max(0, Math.min(STEPS.length - 1, step));
    saveDraft();
    render();
    window.scrollTo({ top: root.offsetTop - 8, behavior: "smooth" });
  }
  // A step can be opened once the institution and gut feeling are in.
  function reachable(i) { return i === 0 || (state.org && (i === 1 || state.overall)); }

  function drawProgress() {
    progress.textContent = "";
    STEPS.forEach(function (s, i) {
      var li = el("li");
      var b = button("rv-pill", (i + 1) + ". " + s.label, function () { go(i); });
      b.disabled = !reachable(i);
      if (i === state.step) b.setAttribute("aria-current", "step");
      li.appendChild(b);
      progress.appendChild(li);
    });
  }

  // Five buttons, 1 on the left. `value` is the stored score, `ghost` a default shown faintly.
  function scale(labels, value, onPick, opts) {
    opts = opts || {};
    var row = el("div", "rv-scale" + (opts.big ? " big" : ""));
    row.setAttribute("role", "group");
    if (opts.name) row.setAttribute("aria-label", opts.name);
    labels.forEach(function (label, i) {
      var n = i + 1;
      var b = button("rv-score", null, function () { onPick(n === value && !opts.big ? 0 : n); });
      b.appendChild(el("span", "n", String(n)));
      if (opts.big || opts.words) b.appendChild(el("span", "w", label));
      b.setAttribute("aria-label", n + "점 " + label);
      b.setAttribute("aria-pressed", n === value ? "true" : "false");
      if (!value && n === opts.ghost) b.classList.add("ghost");
      row.appendChild(b);
    });
    if (!opts.big && !opts.words) {
      var ends = el("div", "rv-ends");
      ends.appendChild(el("span", null, labels[0]));
      ends.appendChild(el("span", null, labels[labels.length - 1]));
      var wrap = el("div", "rv-scale-wrap");
      wrap.appendChild(row);
      wrap.appendChild(ends);
      return wrap;
    }
    return row;
  }

  function heading(text, sub) {
    var frag = document.createDocumentFragment();
    var h = el("h2", "rv-q", text);
    h.tabIndex = -1;
    frag.appendChild(h);
    if (sub) frag.appendChild(el("p", "rv-sub", sub));
    return frag;
  }

  function nav(nextLabel, onNext, skip) {
    var bar = el("div", "rv-nav");
    if (state.step > 0) bar.appendChild(button("btn btn-gray btn-lg rv-back", "‹ 이전", function () { go(state.step - 1); }));
    if (skip) bar.appendChild(button("btn btn-line btn-lg", "건너뛰기", skip));
    if (onNext) bar.appendChild(button("btn btn-primary btn-lg rv-next", nextLabel, onNext));
    return bar;
  }

  // --- steps -----------------------------------------------------------------

  function stepOrg() {
    box.appendChild(heading("어느 기관을 평가할까요?", "기관 이름이나 대학 이름 일부만 써도 찾아져요."));
    var label = el("label", "search rv-search");
    label.appendChild(el("span", "sr-only", "기관 이름"));
    var input = el("input");
    input.type = "search";
    input.placeholder = "예: 경희대, 언어교육원";
    input.value = state.org;
    input.autocomplete = "off";
    label.appendChild(input);
    box.appendChild(label);
    var list = el("ul", "rv-orgs");
    box.appendChild(list);

    function pick(name) {
      state.org = name;
      go(1);
    }
    function squash(s) { return s.replace(/\s+/g, "").toLowerCase(); }
    function update() {
      var q = squash(input.value);
      list.textContent = "";
      var hits = q ? DATA.orgs.filter(function (o) { return squash(o).indexOf(q) !== -1; }).slice(0, 8) : [];
      hits.forEach(function (name) {
        var li = el("li");
        li.appendChild(button("rv-org", name, function () { pick(name); }));
        list.appendChild(li);
      });
      var typed = input.value.trim();
      if (typed && !hits.some(function (h) { return squash(h) === squash(typed); })) {
        var li = el("li");
        li.appendChild(button("rv-org add", "“" + typed + "”(으)로 평가하기", function () { pick(typed.slice(0, 80)); }));
        list.appendChild(li);
      }
    }
    input.addEventListener("input", update);
    input.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter") return;
      var first = list.querySelector("button");
      if (first) first.click();
    });
    update();
    setTimeout(function () { input.focus(); }, 0);
  }

  function stepOverall() {
    box.appendChild(heading(state.org, "한마디로, 이곳은 어땠나요?"));
    box.appendChild(scale(DATA.labels.overall, state.overall, function (n) {
      state.overall = n;
      saveDraft();
      render();
      // Let the pressed state show before moving on.
      setTimeout(function () { go(2); }, 250);
    }, { big: true, name: "첫인상" }));
    box.appendChild(el("p", "rv-hint", "키보드 1~5로도 고를 수 있어요."));
    box.appendChild(nav(null, null));
  }

  function stepMemory() {
    box.appendChild(heading("가장 기억에 남는 건 뭔가요?", "여러 개 골라도 되고, 없으면 건너뛰세요. 고른 영역부터 점수를 물어볼게요."));
    [["good", "좋았던 점", "bad"], ["bad", "아쉬웠던 점", "good"]].forEach(function (g) {
      var key = g[0], other = g[2];
      var group = el("div", "rv-group " + key);
      group.appendChild(el("h3", "rv-group-title", g[1]));
      var chips = el("div", "rv-chips");
      DATA.areas.forEach(function (a) {
        var b = button("rv-chip", a.chip, function () {
          if (has(state[key], a.key)) {
            state[key] = without(state[key], a.key);
          } else {
            state[key] = state[key].concat(a.key);
            state[other] = without(state[other], a.key); // one side per area
          }
          saveDraft();
          render();
        });
        b.setAttribute("aria-pressed", has(state[key], a.key) ? "true" : "false");
        chips.appendChild(b);
      });
      group.appendChild(chips);
      box.appendChild(group);
    });
    var picked = state.good.length + state.bad.length;
    box.appendChild(nav("다음", function () { go(3); }, picked ? null : function () { go(3); }));
  }

  // Areas the reviewer named come first: the sore points, then the good ones.
  function areaOrder() {
    var keys = DATA.areas.map(function (a) { return a.key; });
    return state.bad.concat(state.good, keys.filter(function (k) { return !has(state.bad, k) && !has(state.good, k); }));
  }
  function nextUnscored(after) {
    var order = areaOrder();
    var start = order.indexOf(after) + 1;
    for (var i = 0; i < order.length; i++) {
      var k = order[(start + i) % order.length];
      if (!state.areas[k]) return k;
    }
    return null;
  }

  function areaRow(a) {
    var li = el("li", "rv-area");
    li.dataset.area = a.key;
    if (a.key === current) li.classList.add("current");
    var top = el("div", "rv-area-top");
    var name = el("div", "rv-area-name");
    name.appendChild(el("strong", null, a.name));
    if (has(state.bad, a.key)) name.appendChild(el("span", "rv-tag bad", "아쉬웠던 점"));
    if (has(state.good, a.key)) name.appendChild(el("span", "rv-tag good", "좋았던 점"));
    top.appendChild(name);
    var chosen = state.areas[a.key];
    top.appendChild(el("span", "rv-chosen", chosen ? DATA.labels.area[chosen - 1] : "모르면 비워 두세요"));
    li.appendChild(top);
    li.appendChild(scale(DATA.labels.area, chosen || 0, function (n) {
      if (n) state.areas[a.key] = n; else delete state.areas[a.key];
      current = n ? nextUnscored(a.key) : a.key;
      saveDraft();
      render();
      var row = current && box.querySelector('[data-area="' + current + '"]');
      if (row && n) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, { name: a.name }));

    var isOpen = open[a.key];
    var touched = a.items.filter(function (it) { return state.items[it.key]; }).length;
    var more = button("rv-more", (isOpen ? "접기 ▴" : "자세히 ▾") + (touched ? " · " + touched + "개 답함" : ""), function () {
      open[a.key] = !open[a.key];
      render();
    });
    more.setAttribute("aria-expanded", isOpen ? "true" : "false");
    li.appendChild(more);
    if (isOpen) {
      var items = el("ul", "rv-items");
      a.items.forEach(function (it) {
        var item = el("li", "rv-item");
        item.appendChild(el("p", "rv-statement", it.text));
        // The area score shows faintly as the default; only a tap stores an answer.
        item.appendChild(scale(DATA.labels.agree, state.items[it.key] || 0, function (n) {
          if (n) state.items[it.key] = n; else delete state.items[it.key];
          saveDraft();
          render();
        }, { ghost: chosen, name: it.text }));
        items.appendChild(item);
      });
      li.appendChild(items);
    }
    return li;
  }

  function stepAreas() {
    if (current === null || state.areas[current]) current = nextUnscored(null);
    // Sore points open by themselves: that is where the detail matters.
    state.bad.forEach(function (k) { if (open[k] === undefined) open[k] = true; });
    var done = count(state.areas);
    box.appendChild(heading("영역별로 점수를 매겨 주세요",
      "1 매우 나쁨 ~ 5 매우 좋음. 모르는 영역은 비워 두세요. 더 말하고 싶은 영역은 ‘자세히’를 누르세요."));
    box.appendChild(el("p", "rv-count", DATA.areas.length + "개 중 " + done + "개 매김"));
    var list = el("ul", "rv-areas");
    areaOrder().forEach(function (k) { list.appendChild(areaRow(AREA[k])); });
    box.appendChild(list);
    box.appendChild(el("p", "rv-hint", "키보드 1~5를 누르면 파란 테두리의 영역에 점수가 들어가요."));
    box.appendChild(nav("다음", function () { go(4); }));
  }

  function stepFacts() {
    box.appendChild(heading("근무 조건을 알려 주세요", "아는 것만 고르세요. 한 번 더 누르면 지워져요."));
    DATA.facts.forEach(function (f) {
      var group = el("div", "rv-group");
      group.appendChild(el("h3", "rv-group-title", f.label));
      var chips = el("div", "rv-chips");
      chips.setAttribute("role", "group");
      chips.setAttribute("aria-label", f.label);
      f.options.forEach(function (opt) {
        var b = button("rv-chip", opt, function () {
          if (state.facts[f.key] === opt) delete state.facts[f.key]; else state.facts[f.key] = opt;
          saveDraft();
          render();
        });
        b.setAttribute("aria-pressed", state.facts[f.key] === opt ? "true" : "false");
        chips.appendChild(b);
      });
      group.appendChild(chips);
      box.appendChild(group);
    });
    box.appendChild(nav("다음", function () { go(5); }, count(state.facts) ? null : function () { go(5); }));
  }

  function summary() {
    var sec = el("section", "rv-summary");
    sec.appendChild(el("h3", "rv-group-title", "보내기 전에 확인해 주세요"));
    var dl = el("dl");
    function line(label, value, step) {
      var row = el("div");
      row.appendChild(el("dt", null, label));
      var dd = el("dd");
      dd.appendChild(el("span", null, value));
      dd.appendChild(button("rv-edit", "고치기", function () { go(step); }));
      row.appendChild(dd);
      dl.appendChild(row);
    }
    line("기관", state.org, 0);
    line("첫인상", DATA.labels.overall[state.overall - 1], 1);
    var named = state.good.map(function (k) { return "👍 " + AREA[k].chip; })
      .concat(state.bad.map(function (k) { return "👎 " + AREA[k].chip; }));
    line("기억에 남는 것", named.join(", ") || "고르지 않음", 2);
    var scored = areaOrder().filter(function (k) { return state.areas[k]; })
      .map(function (k) { return AREA[k].chip + " " + state.areas[k]; });
    line("영역 점수", scored.length ? scored.join(" · ") : "매기지 않음", 3);
    var facts = DATA.facts.filter(function (f) { return state.facts[f.key]; })
      .map(function (f) { return f.label + " " + state.facts[f.key]; });
    line("근무 조건", facts.join(" · ") || "고르지 않음", 4);
    sec.appendChild(dl);
    return sec;
  }

  function stepClosing() {
    box.appendChild(heading("마지막으로", "끌리는 대로 누르세요. 다시 누르면 지워져요."));
    var list = el("ul", "rv-items flat");
    DATA.closing.forEach(function (c) {
      var item = el("li", "rv-item");
      item.appendChild(el("p", "rv-statement", c.text));
      item.appendChild(scale(DATA.labels.agree, state.closing[c.key] || 0, function (n) {
        if (n) state.closing[c.key] = n; else delete state.closing[c.key];
        saveDraft();
        render();
      }, { name: c.text }));
      list.appendChild(item);
    });
    box.appendChild(list);

    var label = el("label", "rv-comment");
    label.appendChild(el("span", "rv-group-title", "후배에게 한마디 한다면? (선택)"));
    var text = el("textarea", "field");
    text.rows = 4;
    text.maxLength = 1000;
    text.placeholder = "예: 강사료는 적지만 동료들이 좋아서 버틸 만해요. 행정 업무는 각오하세요.";
    text.value = state.comment;
    text.addEventListener("input", function () { state.comment = text.value; saveDraft(); });
    label.appendChild(text);
    box.appendChild(label);
    box.appendChild(summary());

    var status = el("p", "rv-status");
    status.setAttribute("role", "status");
    var bar = nav("평가 보내기", null);
    var send = button("btn btn-primary btn-lg rv-next", "평가 보내기", function () { submit(send, status); });
    bar.appendChild(send);
    box.appendChild(bar);
    box.appendChild(status);
  }

  function submit(btn, status) {
    var touchedItems = {};
    Object.keys(state.items).forEach(function (k) { touchedItems[k] = state.items[k]; });
    var payload = {
      org: state.org, overall: state.overall, good: state.good, bad: state.bad, areas: state.areas,
      items: touchedItems, closing: state.closing, facts: state.facts, comment: state.comment
    };
    btn.disabled = true;
    status.textContent = "보내는 중이에요…";
    fetch("api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "same-origin"
    }).then(function (res) {
      if (res.ok) {
        var org = state.org;
        dropDraft();
        state = blank();
        done(org);
        return;
      }
      btn.disabled = false;
      status.textContent = res.status === 401
        ? "관리자 로그인이 풀렸어요. 새로고침해서 다시 로그인한 뒤 보내 주세요. 입력한 내용은 남아 있어요."
        : "저장하지 못했어요(" + res.status + "). 잠시 후 다시 눌러 주세요. 입력한 내용은 남아 있어요.";
    }).catch(function () {
      btn.disabled = false;
      status.textContent = "서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 눌러 주세요. 입력한 내용은 남아 있어요.";
    });
  }

  function done(org) {
    progress.textContent = "";
    box.textContent = "";
    box.appendChild(heading("고마워요!", org + " 평가가 저장됐어요."));
    var bar = el("div", "rv-nav");
    bar.appendChild(button("btn btn-primary btn-lg", "다른 기관도 평가하기", function () {
      history.replaceState(null, "", location.pathname);
      go(0);
    }));
    var back = el("a", "btn btn-line btn-lg", "공고 보러 가기");
    back.href = "index.html";
    bar.appendChild(back);
    box.appendChild(bar);
    box.querySelector(".rv-q").focus();
  }

  var DRAW = [stepOrg, stepOverall, stepMemory, stepAreas, stepFacts, stepClosing];
  function render() {
    if (!reachable(state.step)) state.step = state.org ? 1 : 0;
    var focusQ = box.dataset.shown !== String(state.step);
    box.textContent = "";
    box.dataset.shown = String(state.step);
    drawProgress();
    DRAW[state.step]();
    // Move focus to the new question only when the step changed, not on every tap.
    if (focusQ && state.step !== 0) {
      var q = box.querySelector(".rv-q");
      if (q) q.focus({ preventScroll: true });
    }
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var t = ev.target.tagName;
    if (t === "INPUT" || t === "TEXTAREA") return;
    var n = Number(ev.key);
    if (!(n >= 1 && n <= 5)) return;
    var step = STEPS[state.step].key;
    var target = null;
    if (step === "overall") target = box.querySelectorAll(".rv-scale.big .rv-score")[n - 1];
    if (step === "areas" && current) {
      target = box.querySelectorAll('[data-area="' + current + '"] > .rv-scale-wrap .rv-score')[n - 1];
    }
    if (target) { ev.preventDefault(); target.click(); }
  });

  render();
})();
