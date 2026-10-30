/* 나도 평가하기 (test build only). Two ways in, one set of answers:
   직접 평가하기 scores statements directly (area → statement → 1-5), and the
   default story is told like a personality quiz: a guide, then
   one working day in scenes (출근길 → 교무실 → 수업 → 월급날 → …). Each scene
   asks one or two everyday questions and offers more at its end; answers are
   situations, and each carries the score of a statement in review_items.py.
   Nothing is required: "잘 모르겠어요" skips, "여기까지 할게요" ends at any
   point. Before anything is sent, 내 답 확인 lists every answer to change.
   Every screen is a history entry, so the phone's back gesture goes back one
   question. A draft stays in this browser. */
(function () {
  "use strict";

  var root = document.querySelector("[data-review]");
  if (!root) return;
  var DATA = JSON.parse(document.getElementById("reviewData").textContent);
  var STORY = DATA.story;
  var box = root.querySelector("[data-review-box]");
  var org = (new URLSearchParams(location.search).get("org") || "").trim().slice(0, 80);

  // --- answers, kept per institution until sent ---------------------------------
  function draftKey() { return "review-draft-v3:" + org; }
  function blank() { return { items: {}, facts: {}, comment: "", more: {}, at: null, mode: "story" }; }
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

  // --- DOM helpers -------------------------------------------------------------------
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
  function q(name) { return encodeURIComponent(name); }
  function ratingHref() { return "rating.html?org=" + q(org); }
  function story(text) { return text.replace(/\{org\}/g, org); }
  function title(text) {
    var h = el("h1", "rv-q", text);
    h.tabIndex = -1;
    return h;
  }

  // --- the path through the story ------------------------------------------------------
  // A position is {s: "intro" | "q" | "offer" | "note" | "result", c: scene, part: "core" | "more", i}.
  function sceneStart(c) {
    return c < STORY.length ? { s: "q", c: c, part: "core", i: 0 } : { s: "note" };
  }
  function next(pos) {
    if (pos.s === "intro") return sceneStart(0);
    var scene = STORY[pos.c];
    if (pos.s === "offer") return answers.more[scene.key] ? { s: "q", c: pos.c, part: "more", i: 0 } : sceneStart(pos.c + 1);
    if (pos.s === "q") {
      var list = scene[pos.part];
      if (pos.i + 1 < list.length) return { s: "q", c: pos.c, part: pos.part, i: pos.i + 1 };
      if (pos.part === "core" && scene.more.length) return { s: "offer", c: pos.c };
      return sceneStart(pos.c + 1);
    }
    return { s: "note" };
  }
  var pos = { s: "intro" };
  function go(to) {
    pos = to;
    answers.at = to;
    saveDraft();
    history.pushState(to, "");
    render(true);
  }
  function advance() { go(next(pos)); }
  window.addEventListener("popstate", function (ev) {
    pos = ev.state || { s: "intro" };
    render(true);
  });

  // --- shared pieces -------------------------------------------------------------------
  function sceneHeader(c) {
    var head = el("div", "st-head");
    var label = el("p", "st-scene-no", "장면 " + (c + 1) + " / " + STORY.length + " · " + STORY[c].title);
    head.appendChild(label);
    var track = el("div", "st-track");
    track.setAttribute("aria-hidden", "true");
    var fill = el("span", "st-track-fill");
    fill.style.width = ((c + 1) / STORY.length * 100) + "%";
    track.appendChild(fill);
    head.appendChild(track);
    return head;
  }
  // ‹ 이전 and the way out, on every question.
  function bottomBar(doneLabel) {
    var bar = el("div", "rv-bar");
    var inner = el("div", "rv-bar-in");
    inner.appendChild(button("btn btn-gray btn-lg", "‹ 이전", function () { history.back(); }));
    inner.appendChild(button("btn btn-line btn-lg rv-done", doneLabel || "여기까지 할게요", finish));
    bar.appendChild(inner);
    var status = el("p", "rv-status");
    status.setAttribute("role", "status");
    bar.appendChild(status);
    return bar;
  }

  // --- screens -------------------------------------------------------------------------
  // Two ways in, one set of answers: the story, or scoring statements directly.
  function start(mode) {
    answers.mode = mode;
    go(mode === "direct" ? { s: "areas" } : sceneStart(0));
  }
  function modeCard(name, desc, tag, onClick, primary) {
    var b = button("st-mode" + (primary ? " primary" : ""), null, onClick);
    var top = el("span", "st-mode-top");
    top.appendChild(el("span", "st-mode-name", name));
    top.appendChild(el("span", "st-mode-tag", tag));
    b.appendChild(top);
    b.appendChild(el("span", "st-mode-desc", desc));
    return b;
  }
  function drawIntro() {
    var card = el("div", "st-intro");
    card.appendChild(el("p", "rv-kicker", "나도 평가하기 · " + org));
    card.appendChild(title("자, 이제 평가해 볼까요?"));
    card.appendChild(el("p", "st-lead", "편한 방법을 고르세요."));
    var resume = answers.at && answers.at.s !== "intro" && answeredCount();
    if (resume) {
      var again = el("div", "st-actions");
      again.appendChild(button("btn btn-primary btn-lg", "하던 평가 이어서 하기", function () { go(answers.at); }));
      card.appendChild(again);
      card.appendChild(el("p", "st-time", "아래에서 고르면 처음부터 다시 시작해요."));
    }
    var modes = el("div", "st-modes");
    function fresh(mode) { return function () { answers = blank(); start(mode); }; }
    modes.appendChild(modeCard("이야기로 평가하기", "일하던 하루를 따라가며 상황에 맞는 답을 골라요. 심리테스트처럼 가볍게.",
      "약 3분", fresh("story"), !resume));
    modes.appendChild(modeCard("직접 평가하기", "급여, 분위기 같은 항목을 골라 문장마다 1~5점을 바로 매겨요.",
      "원하는 것만", fresh("direct")));
    card.appendChild(modes);
    var how = el("ul", "st-how");
    ["정답도 필수 질문도 없어요. 모르는 건 넘어가세요.",
     "언제든 멈출 수 있고, 그때까지 고른 것만 반영돼요.",
     "보내기 전에 내 답을 모두 확인하고 고칠 수 있어요.",
     "이름도 경력도 묻지 않아요."].forEach(function (t) { how.appendChild(el("li", null, t)); });
    card.appendChild(how);
    var later = el("a", "st-later", "다음에 할게요");
    later.href = ratingHref();
    var foot = el("div", "st-actions");
    foot.appendChild(later);
    card.appendChild(foot);
    box.appendChild(card);
  }

  // --- 직접 평가하기: area → statement → 1-5 ------------------------------------------
  var AREA = {};
  DATA.areas.forEach(function (a) { AREA[a.key] = a; });
  var FACT = {};
  DATA.facts.forEach(function (f) { FACT[f.key] = f; });
  function scoreText(s) { return s + " · " + DATA.labels[s - 1]; }

  function directCard(name, done, total, onClick) {
    var b = button("rv-card" + (done ? " has" : ""), null, onClick);
    b.appendChild(el("span", "rv-card-name", name));
    b.appendChild(el("span", "rv-card-state", done ? "✓ " + done + (total ? " / " + total : "") : "›"));
    return b;
  }
  function drawAreas() {
    var head = el("div", "st-offer");
    head.appendChild(el("p", "rv-kicker", "직접 평가하기 · " + org));
    head.appendChild(title("어떤 항목을 평가할까요?"));
    head.appendChild(el("p", "rv-sub", "아는 항목만 골라 누르세요. 하나만 해도 돼요."));
    box.appendChild(head);
    var grid = el("div", "rv-cards");
    DATA.areas.forEach(function (a) {
      var done = a.items.filter(function (it) { return answers.items[it.key]; }).length;
      grid.appendChild(directCard(a.name, done, a.items.length, function () { go({ s: "items", area: a.key }); }));
    });
    grid.appendChild(directCard("근무 조건 (강사료·시수 등)", Object.keys(answers.facts).length, DATA.facts.length,
      function () { go({ s: "items", area: "facts" }); }));
    grid.appendChild(directCard("후배에게 쪽지", answers.comment.trim() ? 1 : 0, 0,
      function () { go({ s: "note", edit: "areas" }); }));
    box.appendChild(grid);
    box.appendChild(bottomBar("다 했어요"));
  }
  function drawItems() {
    var facts = pos.area === "facts";
    var head = el("div", "st-offer");
    head.appendChild(el("p", "rv-kicker", "직접 평가하기"));
    head.appendChild(title(facts ? "근무 조건" : AREA[pos.area].name));
    head.appendChild(el("p", "rv-sub", "누르면 점수를 고를 수 있어요. 모르는 건 건너뛰세요."));
    box.appendChild(head);
    var list = el("div", "rv-list");
    var rows = facts
      ? DATA.facts.map(function (f) { return { text: f.label, answer: answers.facts[f.key], key: f.key }; })
      : AREA[pos.area].items.map(function (it) {
        var s = answers.items[it.key];
        return { text: it.text, answer: s ? scoreText(s) : null, key: it.key };
      });
    rows.forEach(function (r) {
      var b = button("rv-stmt" + (r.answer ? " has" : ""), null, function () { go({ s: "score", area: pos.area, key: r.key }); });
      b.appendChild(el("span", "rv-stmt-text", r.text));
      b.appendChild(el("span", "rv-stmt-answer", r.answer || "답하기 ›"));
      list.appendChild(b);
    });
    box.appendChild(list);
    box.appendChild(bottomBar("다 했어요"));
  }
  // Picking returns to wherever the statement was opened from (its list, or 내 답 확인).
  function drawScore() {
    var facts = pos.area === "facts";
    var current = facts ? answers.facts[pos.key] : answers.items[pos.key];
    var text = facts ? FACT[pos.key].label : itemText(pos.key);
    var head = el("div", "st-offer");
    head.appendChild(el("p", "rv-kicker", facts ? "근무 조건" : AREA[pos.area].name));
    head.appendChild(title(text));
    head.appendChild(el("p", "rv-sub", facts ? "해당하는 것을 고르세요." : "얼마나 그런가요?"));
    box.appendChild(head);
    function pick(v) {
      if (facts) answers.facts[pos.key] = v; else answers.items[pos.key] = v;
      saveDraft();
      setTimeout(function () { history.back(); }, 200); // let the press show
    }
    var choices = el("div", facts ? "rv-options" : "rv-scale");
    (facts ? FACT[pos.key].options : [1, 2, 3, 4, 5]).forEach(function (v, i) {
      var b = button(facts ? "rv-option" : "rv-score", facts ? v : null, function () {
        b.setAttribute("aria-pressed", "true");
        pick(v);
      });
      if (!facts) {
        b.appendChild(el("span", "n", String(v)));
        b.appendChild(el("span", "w", DATA.labels[i]));
        b.setAttribute("aria-label", v + "점 " + DATA.labels[i]);
      }
      b.setAttribute("aria-pressed", v === current ? "true" : "false");
      choices.appendChild(b);
    });
    box.appendChild(choices);
    if (current != null) {
      box.appendChild(button("st-skip", "답 지우기", function () {
        if (facts) delete answers.facts[pos.key]; else delete answers.items[pos.key];
        saveDraft();
        history.back();
      }));
    }
    box.appendChild(editBar(pos.edit === "check" ? "‹ 내 답 확인으로 돌아가기" : "‹ 돌아가기"));
  }
  function itemText(key) {
    for (var i = 0; i < DATA.areas.length; i++) {
      for (var j = 0; j < DATA.areas[i].items.length; j++) {
        if (DATA.areas[i].items[j].key === key) return DATA.areas[i].items[j].text;
      }
    }
    return "";
  }

  // Opened from the check screen (pos.edit), a question returns there once answered.
  function drawQuestion() {
    var scene = STORY[pos.c];
    var question = scene[pos.part][pos.i];
    var after = pos.edit ? function () { saveDraft(); history.back(); } : advance;
    box.appendChild(sceneHeader(pos.c));
    // The scene is narrated once, above its first question.
    if (pos.part === "core" && pos.i === 0 && !pos.edit) box.appendChild(el("p", "st-scene", story(scene.scene)));
    box.appendChild(title(story(question.q)));
    var current = answerOf(question);
    var list = el("div", "st-options");
    question.options.forEach(function (o) {
      var value = question.item ? o.score : o.text;
      var b = button("st-option", o.text, function () {
        if (question.item) answers.items[question.item] = value; else answers.facts[question.fact] = value;
        b.setAttribute("aria-pressed", "true");
        setTimeout(after, 200); // let the press show
      });
      // Answers to one question never share a score (a test checks), so the value marks the pick.
      b.setAttribute("aria-pressed", current === value ? "true" : "false");
      list.appendChild(b);
    });
    box.appendChild(list);
    box.appendChild(button("st-skip", pos.edit && current != null ? "답 지우기" : "잘 모르겠어요 ›", function () {
      if (question.item) delete answers.items[question.item]; else delete answers.facts[question.fact];
      after();
    }));
    if (pos.edit) box.appendChild(editBar("‹ 내 답 확인으로 돌아가기"));
    else box.appendChild(bottomBar());
  }
  function answerOf(question) {
    return question.item ? answers.items[question.item] : answers.facts[question.fact];
  }
  function answerText(question) {
    var v = answerOf(question);
    if (v == null) return null;
    if (question.fact) return v;
    for (var i = 0; i < question.options.length; i++) if (question.options[i].score === v) return question.options[i].text;
    // Scored directly with a value the story has no answer for (say 3).
    return scoreText(v);
  }
  function editBar(label) {
    var bar = el("div", "rv-bar");
    var inner = el("div", "rv-bar-in");
    inner.appendChild(button("btn btn-gray btn-lg rv-done", label, function () { history.back(); }));
    bar.appendChild(inner);
    return bar;
  }

  // --- 내 답 확인: everything picked, each one changeable, before sending ---------------
  function drawCheck() {
    var head = el("div", "st-offer");
    head.appendChild(el("p", "rv-kicker", "보내기 전에"));
    head.appendChild(title("내 답을 확인해 주세요"));
    head.appendChild(el("p", "rv-sub", "바꾸고 싶은 답을 누르면 그 질문으로 가요. 고르면 다시 여기로 돌아와요."));
    box.appendChild(head);
    var open = [];
    // Grouped the way the reviewer answered: by scene for the story, by area when scoring directly.
    var groups = answers.mode === "direct" ? directGroups() : storyGroups();
    groups.forEach(function (g) {
      var rows = [];
      g.rows.forEach(function (r) {
        if (r.answer == null) open.push(r); else rows.push(checkRow(r.q, r.answer, r.to));
      });
      if (!rows.length) return;
      var sec = el("section", "ck-scene");
      sec.appendChild(el("h2", "ck-title", g.title));
      rows.forEach(function (row) { sec.appendChild(row); });
      box.appendChild(sec);
    });
    var note = el("section", "ck-scene");
    note.appendChild(el("h2", "ck-title", "후배에게 쪽지"));
    note.appendChild(checkRow("남긴 말", answers.comment.trim() || "쓰지 않음", { s: "note", edit: "check" }));
    box.appendChild(note);
    // Questions passed by can still be answered here, folded away so they do not press.
    if (open.length) {
      var more = el("details", "ck-open");
      more.appendChild(el("summary", null, "건너뛴 질문도 볼 수 있어요 (" + open.length + "개)"));
      open.forEach(function (r) { more.appendChild(checkRow(r.group, r.q, r.to, "답하기")); });
      box.appendChild(more);
    }
    var actions = el("div", "st-actions");
    actions.appendChild(button("btn btn-primary btn-lg", "이대로 보내기", send));
    actions.appendChild(button("btn btn-line btn-lg", "‹ 이전", function () { history.back(); }));
    box.appendChild(actions);
    var status = el("p", "rv-status");
    status.setAttribute("role", "status");
    box.appendChild(status);
  }
  function storyGroups() {
    return STORY.map(function (scene, c) {
      var title = "장면 " + (c + 1) + " · " + scene.title;
      var rows = [];
      ["core", "more"].forEach(function (part) {
        scene[part].forEach(function (question, i) {
          rows.push({ group: scene.title, q: story(question.q), answer: answerText(question),
                      to: { s: "q", c: c, part: part, i: i, edit: "check" } });
        });
      });
      return { title: title, rows: rows };
    });
  }
  function directGroups() {
    var groups = DATA.areas.map(function (a) {
      return { title: a.name, rows: a.items.map(function (it) {
        var s = answers.items[it.key];
        return { group: a.name, q: it.text, answer: s ? scoreText(s) : null,
                 to: { s: "score", area: a.key, key: it.key, edit: "check" } };
      }) };
    });
    groups.push({ title: "근무 조건", rows: DATA.facts.map(function (f) {
      return { group: "근무 조건", q: f.label, answer: answers.facts[f.key] || null,
               to: { s: "score", area: "facts", key: f.key, edit: "check" } };
    }) });
    return groups;
  }
  function checkRow(question, answer, to, verb) {
    var b = button("ck-row", null, function () { go(to); });
    var text = el("span", "ck-text");
    text.appendChild(el("span", "ck-q", question));
    text.appendChild(el("span", "ck-a", answer));
    b.appendChild(text);
    b.appendChild(el("span", "ck-edit", (verb || "고치기") + " ›"));
    return b;
  }
  function drawOffer() {
    var scene = STORY[pos.c];
    box.appendChild(sceneHeader(pos.c));
    var mid = el("div", "st-offer");
    mid.appendChild(title("‘" + scene.title + "’, 조금 더 이야기해 볼까요?"));
    mid.appendChild(el("p", "rv-sub", "질문이 " + scene.more.length + "개 더 있어요. 넘어가도 괜찮아요."));
    var actions = el("div", "st-actions");
    actions.appendChild(button("btn btn-primary btn-lg", "더 이야기할래요", function () {
      answers.more[scene.key] = true;
      advance();
    }));
    actions.appendChild(button("btn btn-line btn-lg", "다음 장면으로 ›", function () {
      answers.more[scene.key] = false;
      advance();
    }));
    mid.appendChild(actions);
    box.appendChild(mid);
    box.appendChild(bottomBar());
  }

  function drawNote() {
    if (pos.edit) return drawNoteEdit();
    var mid = el("div", "st-offer");
    mid.appendChild(el("p", "rv-kicker", "이야기의 끝"));
    mid.appendChild(title("후배에게 쪽지 한 장을 남긴다면?"));
    mid.appendChild(el("p", "rv-sub", "한 줄이면 충분해요. 쓰지 않아도 괜찮아요."));
    box.appendChild(mid);
    box.appendChild(noteBox());
    var actions = el("div", "st-actions");
    actions.appendChild(button("btn btn-primary btn-lg", "남기고 마치기", finish));
    actions.appendChild(button("btn btn-line btn-lg", "쓰지 않고 마치기", function () {
      answers.comment = "";
      finish();
    }));
    box.appendChild(actions);
  }
  function noteBox() {
    var label = el("label", "rv-comment");
    label.appendChild(el("span", "sr-only", "후배에게 남기는 쪽지"));
    var text = el("textarea", "field");
    text.rows = 4;
    text.maxLength = 1000;
    text.placeholder = "예: 강사료는 적지만 동료들이 좋아서 버틸 만해요. 행정 업무는 각오하세요.";
    text.value = answers.comment;
    text.addEventListener("input", function () { answers.comment = text.value; saveDraft(); });
    label.appendChild(text);
    return label;
  }
  function drawNoteEdit() {
    var mid = el("div", "st-offer");
    mid.appendChild(title("후배에게 남기는 쪽지"));
    mid.appendChild(el("p", "rv-sub", "쓰거나 고치거나 지워도 돼요."));
    box.appendChild(mid);
    box.appendChild(noteBox());
    box.appendChild(editBar(pos.edit === "check" ? "‹ 내 답 확인으로 돌아가기" : "‹ 돌아가기"));
  }

  // The quiz result: the area remembered best, and the one remembered worst.
  function drawResult() {
    var scores = {};
    DATA.areas.forEach(function (a) {
      var got = a.items.map(function (it) { return answers.items[it.key]; }).filter(Boolean);
      if (got.length) scores[a.key] = got.reduce(function (x, y) { return x + y; }, 0) / got.length;
    });
    var keys = Object.keys(scores).sort(function (a, b) { return scores[b] - scores[a]; });
    var best = keys[0], worst = keys[keys.length - 1];
    var card = el("div", "st-result");
    card.appendChild(el("p", "rv-kicker", "당신이 기억하는 " + org + "은(는)"));
    var head = best && scores[best] >= 3.5 ? DATA.types[best][0] : "평범하지만 무난한 곳";
    card.appendChild(title(head));
    if (worst && worst !== best && scores[worst] <= 2.5) card.appendChild(el("p", "st-but", "다만, " + DATA.types[worst][1]));
    card.appendChild(el("p", "rv-sub", "고른 답은 이름 없이 " + org + " 평가에 더해졌어요. 고마워요!"));
    var actions = el("div", "st-actions");
    var see = el("a", "btn btn-primary btn-lg", "다른 사람들의 평가 보기");
    see.href = ratingHref();
    var map = el("a", "btn btn-line btn-lg", "지도로 돌아가기");
    map.href = "index.html";
    actions.appendChild(see);
    actions.appendChild(map);
    card.appendChild(actions);
    box.appendChild(card);
  }

  // --- sending -------------------------------------------------------------------------
  // With nothing picked, finishing just goes back to the results: no nagging.
  var sent = null;
  // Every way out (the story's end, 여기까지 할게요) passes 내 답 확인 first.
  function finish() {
    if (!answeredCount()) {
      location.href = ratingHref();
      return;
    }
    go({ s: "check" });
  }
  function send() {
    var status = box.querySelector(".rv-status");
    var buttons = box.querySelectorAll("button");
    Array.prototype.forEach.call(buttons, function (b) { b.disabled = true; });
    status.textContent = "보내는 중이에요…";
    fetch("api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ org: org, items: answers.items, facts: answers.facts, comment: answers.comment }),
      credentials: "same-origin"
    }).then(function (res) {
      if (res.ok) {
        sent = answers;
        dropDraft();
        pos = { s: "result" };
        history.replaceState(pos, "");
        render(true);
        answers = blank();
        return;
      }
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      status.textContent = res.status === 401
        ? "관리자 로그인이 풀렸어요. 새로고침해서 다시 로그인한 뒤 눌러 주세요. 고른 답은 남아 있어요."
        : "저장하지 못했어요(" + res.status + "). 잠시 후 다시 눌러 주세요. 고른 답은 남아 있어요.";
    }).catch(function () {
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      status.textContent = "서버에 연결하지 못했어요. 인터넷 연결을 확인하고 다시 눌러 주세요. 고른 답은 남아 있어요.";
    });
  }

  // --- no institution yet: find one -----------------------------------------------------
  function drawSearch() {
    var head = el("div", "st-offer");
    head.appendChild(el("p", "rv-kicker", "나도 평가하기"));
    head.appendChild(title("어느 기관을 평가할까요?"));
    head.appendChild(el("p", "rv-sub", "기관 이름이나 대학 이름 일부만 써도 찾아져요."));
    box.appendChild(head);
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
        li.appendChild(button("rv-org", name, function () { pick(name); }));
        list.appendChild(li);
      });
      var typed = input.value.trim();
      if (typed && !hits.some(function (h) { return squash(h) === s; })) {
        var li = el("li");
        li.appendChild(button("rv-org add", "“" + typed + "”(으)로 평가하기", function () { pick(typed); }));
        list.appendChild(li);
      }
    });
    setTimeout(function () { input.focus(); }, 0);
  }

  var DRAW = {
    intro: drawIntro, q: drawQuestion, offer: drawOffer, note: drawNote, check: drawCheck, result: drawResult,
    areas: drawAreas, items: drawItems, score: drawScore
  };
  function render(moved) {
    box.textContent = "";
    box.dataset.view = pos.s;
    if (!org) { drawSearch(); return; }
    if (pos.s === "result") {
      // The result reads what was sent; after a reload it is gone, so start over.
      if (!sent) pos = { s: "intro" }; else answers = sent;
    }
    (DRAW[pos.s] || drawIntro)();
    if (pos.s === "result") answers = blank();
    if (moved) {
      window.scrollTo(0, 0);
      var h = box.querySelector(".rv-q");
      if (h) h.focus({ preventScroll: true });
    }
  }

  // A reload keeps the screen the reviewer was on.
  if (history.state && history.state.s && history.state.s !== "result") pos = history.state;
  else history.replaceState(pos, "");
  render(false);
})();
