/* 기관 평가 결과 (test build only). With ?org= it shows that institution's
   averages, job facts and comments from /test/api/ratings; without, a search.
   "나도 평가하기" leads to review.html for the same institution. */
(function () {
  "use strict";

  var root = document.querySelector("[data-review]");
  if (!root) return;
  var DATA = JSON.parse(document.getElementById("reviewData").textContent);
  var box = root.querySelector("[data-review-box]");
  var org = (new URLSearchParams(location.search).get("org") || "").trim();

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function link(cls, text, href) {
    var a = el("a", cls, text);
    a.href = href;
    return a;
  }
  function q(name) { return encodeURIComponent(name); }
  function squash(s) { return s.replace(/\s+/g, "").toLowerCase(); }

  function load(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (res) {
      if (!res.ok) throw new Error(res.status === 401 ? "login" : "status");
      return res.json();
    });
  }
  function failed(err) {
    var msg = err && err.message === "login"
      ? "관리자 로그인이 풀렸어요. 새로고침해서 다시 로그인해 주세요."
      : "평가를 불러오지 못했어요. 잠시 후 새로고침해 주세요.";
    box.appendChild(el("p", "rv-note", msg));
  }

  function bar(avg) {
    var track = el("span", "rt-bar");
    var fill = el("span", "rt-fill");
    fill.style.width = (avg / 5 * 100) + "%";
    track.appendChild(fill);
    return track;
  }

  // --- search: no institution picked yet ---------------------------------------
  function search(counts) {
    box.appendChild(link("back", "‹ 지도로 돌아가기", "index.html"));
    var head = el("div", "rv-center");
    head.appendChild(el("h1", "rv-q", "어느 기관의 평가를 볼까요?"));
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
    // Institutions with reviews come first, most reviewed on top.
    var names = DATA.orgs.slice();
    Object.keys(counts).forEach(function (n) { if (names.indexOf(n) === -1) names.push(n); });
    names.sort(function (a, b) { return (counts[b] || 0) - (counts[a] || 0); });
    function update() {
      var s = squash(input.value);
      list.textContent = "";
      names.filter(function (n) { return s ? squash(n).indexOf(s) !== -1 : counts[n]; }).slice(0, 10).forEach(function (n) {
        var li = el("li");
        var a = link("rv-org", n, "rating.html?org=" + q(n));
        a.appendChild(el("span", "rv-org-count", counts[n] ? "평가 " + counts[n] + "개" : "평가 없음"));
        li.appendChild(a);
        list.appendChild(li);
      });
      if (!list.children.length && !s) list.appendChild(el("li", "rv-note", "아직 평가가 하나도 없어요. 기관을 찾아 첫 평가를 남겨 주세요."));
    }
    input.addEventListener("input", update);
    update();
  }

  // --- one institution -----------------------------------------------------------
  function results(sum) {
    box.appendChild(link("back", "‹ 지도로 돌아가기", "index.html"));
    var head = el("div", "rt-head");
    head.appendChild(el("p", "rv-kicker", "기관 평가"));
    head.appendChild(el("h1", "rv-q", org));
    head.appendChild(el("p", "rv-sub", sum.count ? "평가 " + sum.count + "개 · 이름 없이 모였어요" : "아직 평가가 없어요"));
    var reviewHref = "review.html?org=" + q(org);
    if (sum.count) head.appendChild(link("btn btn-primary btn-lg rt-cta", "나도 평가하기", reviewHref));
    box.appendChild(head);

    if (!sum.count) {
      var empty = el("div", "rt-empty");
      empty.appendChild(el("p", "rt-empty-t", "이곳에서 일해 봤다면 첫 평가를 남겨 주세요."));
      empty.appendChild(el("p", "rv-sub", "아는 것만 몇 개 눌러도 돼요. 이름이나 경력은 묻지 않아요."));
      empty.appendChild(link("btn btn-primary btn-lg rt-cta", "나도 평가하기", reviewHref));
      box.appendChild(empty);
      return;
    }

    var areas = el("div", "rt-areas");
    DATA.areas.forEach(function (a) {
      var total = 0, n = 0;
      a.items.forEach(function (it) {
        var s = sum.items[it.key];
        if (s) { total += s[0]; n += s[1]; }
      });
      if (!n) return;
      var card = el("details", "rt-area");
      var head = el("summary");
      head.appendChild(el("span", "rt-name", a.name));
      head.appendChild(el("strong", "rt-avg", (total / n).toFixed(1)));
      head.appendChild(bar(total / n));
      head.appendChild(el("span", "rt-n", "답 " + n + "개 · 눌러서 자세히"));
      card.appendChild(head);
      var list = el("ul", "rt-items");
      a.items.forEach(function (it) {
        var s = sum.items[it.key];
        var li = el("li");
        li.appendChild(el("p", "rt-text", it.text));
        var line = el("div", "rt-line");
        if (s) {
          line.appendChild(el("strong", "rt-avg sm", (s[0] / s[1]).toFixed(1)));
          line.appendChild(bar(s[0] / s[1]));
          line.appendChild(el("span", "rt-n", s[1] + "명"));
        } else {
          line.appendChild(el("span", "rt-n", "아직 답이 없어요"));
        }
        li.appendChild(line);
        list.appendChild(li);
      });
      card.appendChild(list);
      areas.appendChild(card);
    });
    if (areas.children.length) {
      box.appendChild(el("h2", "rt-title", "영역별 점수"));
      box.appendChild(el("p", "rv-sub", "5점에 가까울수록 좋아요."));
      box.appendChild(areas);
    }

    var facts = DATA.facts.filter(function (f) { return sum.facts[f.key]; });
    if (facts.length) {
      box.appendChild(el("h2", "rt-title", "근무 조건"));
      var dl = el("dl", "rt-facts");
      facts.forEach(function (f) {
        var row = el("div");
        row.appendChild(el("dt", null, f.label));
        var tally = sum.facts[f.key];
        row.appendChild(el("dd", null, f.options.filter(function (o) { return tally[o]; })
          .map(function (o) { return o + " " + tally[o] + "명"; }).join(" · ")));
        dl.appendChild(row);
      });
      box.appendChild(dl);
    }

    if (sum.comments.length) {
      box.appendChild(el("h2", "rt-title", "후배에게 한마디"));
      var ul = el("ul", "rt-comments");
      sum.comments.forEach(function (c) {
        var li = el("li");
        li.appendChild(el("p", null, c.text));
        li.appendChild(el("span", "rt-n", c.on.replace("-", "년 ") + "월"));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }

    var foot = el("div", "rt-foot");
    foot.appendChild(el("p", "rv-sub", "이곳에서 일해 봤나요?"));
    foot.appendChild(link("btn btn-primary btn-lg rt-cta", "나도 평가하기", reviewHref));
    box.appendChild(foot);
  }

  box.textContent = "";
  if (org) {
    document.title = org + " 평가 · " + document.title;
    load("api/ratings?org=" + q(org)).then(results, failed);
  } else {
    load("api/ratings").then(function (data) { search(data.orgs || {}); }, failed);
  }
})();
