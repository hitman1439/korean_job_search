/* 나도 평가하기 (test build only). Three levels, entered in any order:
   area (depth 1) → statement (depth 2) → score (depth 3). A score sends the
   reviewer back to the statements; "뒤로가기" and "완료" are always at the
   bottom, so they can stop whenever. Nothing is required. Each level is a
   browser history entry, so the phone's back gesture works like 뒤로가기.
   Answers stay in this browser (per institution) until they are sent. */
(function () {
  "use strict";

  var root = document.querySelector("[data-review]");
  if (!root) return;
  var DATA = JSON.parse(document.getElementById("reviewData").textContent);
  var box = root.querySelector("[data-review-box]");
  var org = (new URLSearchParams(location.search).get("org") || "").trim().slice(0, 80);
  var FACTS = "facts", COMMENT = "comment";

  var AREA = {};
  DATA.areas.forEach(function (a) { AREA[a.key] = a; });
  var FACT = {};
  DATA.facts.forEach(function (f) { FACT[f.key] = f; });

  // --- answers, kept per institution until sent -------------------------------
  function draftKey() { return "review-draft-v2:" + org; }
  function blank() { return { items: {}, facts: {}, comment: "" }; }
  function loadDraft() {
    try { return JSON.parse(localStorage.getItem(draftKey()) || "null") || blank(); } catch (e) { return blank(); }
  }
  function saveDraft() {
    try { localStorage.setItem(draftKey(), JSON.stringify(answers)); } catch (e) { /* private mode */ }
  }
  function dropDraft() {
    try { localStorage.removeItem(draftKey()); } catch (e) { /* private mode */ }
  }
  var answers = org ? loadDraft() : blank();
  function answeredCount() {
    return Object.keys(answers.items).length + Object.keys(answers.facts).length + (answers.comment.trim() ? 1 : 0);
  }

  // --- small DOM helpers --------------------------------------------------------
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function button(cls, onClick) {
    var b = el("button", cls);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function q(name) { return encodeURIComponent(name); }
  function ratingHref() { return "rating.html?org=" + q(org); }

  function heading(kicker, title, sub) {
    var head = el("div", "rv-center");
    if (kicker) head.appendChild(el("p", "rv-kicker", kicker));
    var h = el("h1", "rv-q", title);
    h.tabIndex = -1;
    head.appendChild(h);
    if (sub) head.appendChild(el("p", "rv-sub", sub));
    return head;
  }

  // 뒤로가기 and 완료 sit at the bottom of every level.
  function bottomBar(onBack) {
    var bar = el("div", "rv-bar");
    var inner = el("div", "rv-bar-in");
    var back = button("btn btn-gray btn-lg", onBack);
    back.textContent = "‹ 뒤로가기";
    var n = answeredCount();
    var done = button("btn btn-primary btn-lg rv-done", finish);
    done.textContent = n ? "완료 · " + n + "개 답함" : "완료";
    inner.appendChild(back);
    inner.appendChild(done);
    bar.appendChild(inner);
    var status = el("p", "rv-status");
    status.setAttribute("role", "status");
    bar.appendChild(status);
    return bar;
  }

  // --- navigation: each level is a history entry -----------------------------------
  var view = { name: "areas" };
  function show(next) {
    history.pushState(next, "");
    view = next;
    render(true);
  }
  function back() { history.back(); }
  window.addEventListener("popstate", function (ev) {
    view = ev.state || { name: "areas" };
    render(true);
  });

  // --- depth 1: areas ---------------------------------------------------------------
  function areaCard(name, done, total, onClick) {
    var b = button("rv-card" + (done ? " has" : ""), onClick);
    b.appendChild(el("span", "rv-card-name", name));
    b.appendChild(el("span", "rv-card-state", done ? "✓ " + done + (total ? " / " + total : "") : "›"));
    return b;
  }
  function drawAreas() {
    box.appendChild(heading("나도 평가하기 · " + org, "어떤 부분을 평가할까요?",
      "아는 것만 골라 누르세요. 하나만 답해도 되고, 언제든 완료할 수 있어요."));
    var grid = el("div", "rv-cards");
    DATA.areas.forEach(function (a) {
      var done = a.items.filter(function (it) { return answers.items[it.key]; }).length;
      grid.appendChild(areaCard(a.name, done, a.items.length, function () { show({ name: "items", area: a.key }); }));
    });
    var facts = Object.keys(answers.facts).length;
    grid.appendChild(areaCard("근무 조건 (강사료·시수 등)", facts, DATA.facts.length, function () { show({ name: "items", area: FACTS }); }));
    grid.appendChild(areaCard("후배에게 한마디", answers.comment.trim() ? 1 : 0, 0, function () { show({ name: COMMENT }); }));
    box.appendChild(grid);
    // Back from the top level leaves the form for the results page.
    box.appendChild(bottomBar(function () { location.href = ratingHref(); }));
  }

  // --- depth 2: statements of one area ----------------------------------------------
  function drawItems() {
    var list = el("div", "rv-list");
    var title;
    if (view.area === FACTS) {
      title = "근무 조건";
      DATA.facts.forEach(function (f) {
        list.appendChild(statement(f.label, answers.facts[f.key] || "", function () { show({ name: "score", area: FACTS, item: f.key }); }));
      });
    } else {
      var a = AREA[view.area];
      title = a.name;
      a.items.forEach(function (it) {
        var s = answers.items[it.key];
        list.appendChild(statement(it.text, s ? s + " · " + DATA.labels[s - 1] : "", function () {
          show({ name: "score", area: a.key, item: it.key });
        }));
      });
    }
    box.appendChild(heading(title, "어떤 것에 답할까요?", "누르면 점수를 고를 수 있어요. 모르는 건 건너뛰세요."));
    box.appendChild(list);
    box.appendChild(bottomBar(back));
  }
  function statement(text, answer, onClick) {
    var b = button("rv-stmt" + (answer ? " has" : ""), onClick);
    b.appendChild(el("span", "rv-stmt-text", text));
    b.appendChild(el("span", "rv-stmt-answer", answer || "답하기 ›"));
    return b;
  }

  // --- depth 3: the score (or a fact's ranges) ---------------------------------------
  // Picking an answer returns to the statements, as a back step would.
  function drawScore() {
    var isFact = view.area === FACTS;
    var current = isFact ? answers.facts[view.item] : answers.items[view.item];
    var text = isFact ? FACT[view.item].label : itemText(view.item);
    box.appendChild(heading(isFact ? "근무 조건" : AREA[view.area].name, text,
      isFact ? "해당하는 것을 고르세요." : "얼마나 그런가요?"));
    var choices = el("div", isFact ? "rv-options" : "rv-scale");
    var values = isFact ? FACT[view.item].options : [1, 2, 3, 4, 5];
    values.forEach(function (v, i) {
      var b = button(isFact ? "rv-option" : "rv-score", function () {
        if (isFact) answers.facts[view.item] = v; else answers.items[view.item] = v;
        saveDraft();
        b.setAttribute("aria-pressed", "true");
        setTimeout(back, 180); // let the press show
      });
      if (isFact) {
        b.textContent = v;
      } else {
        b.appendChild(el("span", "n", String(v)));
        b.appendChild(el("span", "w", DATA.labels[i]));
        b.setAttribute("aria-label", v + "점 " + DATA.labels[i]);
      }
      b.setAttribute("aria-pressed", v === current ? "true" : "false");
      choices.appendChild(b);
    });
    box.appendChild(choices);
    if (current) {
      var clear = button("rv-clear", function () {
        if (isFact) delete answers.facts[view.item]; else delete answers.items[view.item];
        saveDraft();
        back();
      });
      clear.textContent = "답 지우기";
      box.appendChild(clear);
    }
    box.appendChild(bottomBar(back));
  }
  function itemText(key) {
    for (var i = 0; i < DATA.areas.length; i++) {
      for (var j = 0; j < DATA.areas[i].items.length; j++) {
        if (DATA.areas[i].items[j].key === key) return DATA.areas[i].items[j].text;
      }
    }
    return "";
  }

  // --- 후배에게 한마디 ---------------------------------------------------------------
  function drawComment() {
    box.appendChild(heading("후배에게 한마디", "이곳에 지원하려는 후배에게 한마디 한다면?", "솔직하게 써 주세요. 이름은 남지 않아요."));
    var label = el("label", "rv-comment");
    label.appendChild(el("span", "sr-only", "후배에게 한마디"));
    var text = el("textarea", "field");
    text.rows = 5;
    text.maxLength = 1000;
    text.placeholder = "예: 강사료는 적지만 동료들이 좋아서 버틸 만해요. 행정 업무는 각오하세요.";
    text.value = answers.comment;
    text.addEventListener("input", function () {
      answers.comment = text.value;
      saveDraft();
      var done = box.querySelector(".rv-done");
      var n = answeredCount();
      if (done) done.textContent = n ? "완료 · " + n + "개 답함" : "완료";
    });
    label.appendChild(text);
    box.appendChild(label);
    box.appendChild(bottomBar(back));
  }

  // --- finishing ----------------------------------------------------------------------
  // Nothing answered is fine too: 완료 then just goes back to the results.
  function finish() {
    if (!answeredCount()) {
      location.href = ratingHref();
      return;
    }
    var status = box.querySelector(".rv-status");
    var buttons = box.querySelectorAll(".rv-bar button");
    Array.prototype.forEach.call(buttons, function (b) { b.disabled = true; });
    status.textContent = "보내는 중이에요…";
    fetch("api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org: org, items: answers.items, facts: answers.facts, comment: answers.comment }),
      credentials: "same-origin"
    }).then(function (res) {
      if (res.ok) {
        dropDraft();
        answers = blank();
        history.replaceState({ name: "done" }, "");
        view = { name: "done" };
        render(true);
        return;
      }
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      status.textContent = res.status === 401
        ? "관리자 로그인이 풀렸어요. 새로고침해서 다시 로그인한 뒤 눌러 주세요. 답한 내용은 남아 있어요."
        : "저장하지 못했어요(" + res.status + "). 잠시 후 다시 눌러 주세요. 답한 내용은 남아 있어요.";
    }).catch(function () {
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      status.textContent = "서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 눌러 주세요. 답한 내용은 남아 있어요.";
    });
  }

  function drawDone() {
    box.appendChild(heading(null, "고마워요!", org + " 평가가 저장됐어요."));
    var bar = el("div", "rv-center rv-actions");
    var see = el("a", "btn btn-primary btn-lg", "평가 결과 보기");
    see.href = ratingHref();
    var map = el("a", "btn btn-line btn-lg", "지도로 돌아가기");
    map.href = "index.html";
    bar.appendChild(see);
    bar.appendChild(map);
    box.appendChild(bar);
  }

  // --- no institution yet: find one -------------------------------------------------
  function drawSearch() {
    box.appendChild(heading("나도 평가하기", "어느 기관을 평가할까요?", "기관 이름이나 대학 이름 일부만 써도 찾아져요."));
    var label = el("label", "search rv-search");
    label.appendChild(el("span", "sr-only", "기관 이름"));
    var input = el("input");
    input.type = "search";
    input.placeholder = "예: 경희대, 언어교육원";
    input.autocomplete = "off";
    label.appendChild(input);
    box.appendChild(label);
    var list = el("ul", "rv-orgs");
    box.appendChild(list);
    function squash(s) { return s.replace(/\s+/g, "").toLowerCase(); }
    function pick(name) { location.href = "review.html?org=" + q(name.slice(0, 80)); }
    input.addEventListener("input", function () {
      var s = squash(input.value);
      list.textContent = "";
      var hits = s ? DATA.orgs.filter(function (o) { return squash(o).indexOf(s) !== -1; }).slice(0, 8) : [];
      hits.forEach(function (name) {
        var li = el("li");
        var b = button("rv-org", function () { pick(name); });
        b.textContent = name;
        li.appendChild(b);
        list.appendChild(li);
      });
      var typed = input.value.trim();
      if (typed && !hits.some(function (h) { return squash(h) === s; })) {
        var li = el("li");
        var add = button("rv-org add", function () { pick(typed); });
        add.textContent = "“" + typed + "”(으)로 평가하기";
        li.appendChild(add);
        list.appendChild(li);
      }
    });
    setTimeout(function () { input.focus(); }, 0);
  }

  var DRAW = { areas: drawAreas, items: drawItems, score: drawScore, comment: drawComment, done: drawDone };
  function render(moved) {
    box.textContent = "";
    box.dataset.view = view.name;
    if (!org) { drawSearch(); return; }
    (DRAW[view.name] || drawAreas)();
    if (moved) {
      window.scrollTo(0, 0);
      var h = box.querySelector(".rv-q");
      if (h) h.focus({ preventScroll: true });
    }
  }

  // A reload keeps the level the reviewer was on.
  if (history.state && history.state.name && history.state.name !== "done") view = history.state;
  else history.replaceState(view, "");
  render(false);
})();
