// Public job board behaviour: filters, Kakao map, D-day labels, saved/applied
// marks, alert sign-up and the lesson-plan demo. Pages work without it: the
// job list and every job page are plain HTML.
(function () {
  "use strict";

  var SITE = window.SITE || {};

  // --- dates -------------------------------------------------------------
  // Deadlines are Korean dates, so "today" is today in KST wherever the viewer is.
  function todayKST() {
    return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  }

  function daysUntil(deadline) {
    return Math.round((Date.parse(deadline + "T00:00:00Z") - Date.parse(todayKST() + "T00:00:00Z")) / 86400000);
  }

  // Mirrors deadline_badge() in build_site.py.
  function badgeFor(deadline) {
    if (deadline === "rolling") return { text: "상시 모집", cls: "rolling" };
    if (!deadline) return { text: "마감일 미정", cls: "" };
    var d = daysUntil(deadline);
    if (d < 0) return { text: "마감됨", cls: "" };
    if (d === 0) return { text: "오늘 마감", cls: "urgent" };
    if (d <= 7) return { text: "마감 D-" + d, cls: "urgent" };
    return { text: "D-" + d, cls: "" };
  }

  function pinText(deadline) {
    if (deadline === "rolling") return "상시";
    if (!deadline) return "확인";
    var d = daysUntil(deadline);
    return d <= 0 ? "오늘" : "D-" + d;
  }

  // The page was built earlier; recompute every label against today.
  document.querySelectorAll("[data-badge]").forEach(function (el) {
    var b = badgeFor(el.getAttribute("data-badge"));
    el.textContent = b.text;
    // Keep the badge's other classes (badge-title / badge-meta place it).
    el.classList.remove("urgent", "rolling");
    if (b.cls) el.classList.add(b.cls);
  });

  // --- storage (per-viewer conveniences only) ----------------------------
  function readStore(key) {
    try { return JSON.parse(localStorage.getItem(key) || "[]"); } catch (e) { return []; }
  }
  function toggleStore(key, id, on) {
    try {
      var ids = readStore(key).filter(function (x) { return x !== id; });
      if (on) ids.push(id);
      localStorage.setItem(key, JSON.stringify(ids));
    } catch (e) { /* private mode: the mark just won't persist */ }
  }

  // --- Kakao map ---------------------------------------------------------
  var sdkPromise = null;
  function loadKakao() {
    if (sdkPromise) return sdkPromise;
    sdkPromise = new Promise(function (resolve, reject) {
      if (!SITE.kakaoKey) { reject(new Error("no key")); return; }
      var script = document.createElement("script");
      script.src = "https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&libraries=clusterer&appkey=" + encodeURIComponent(SITE.kakaoKey);
      script.onload = function () { window.kakao.maps.load(resolve); };
      script.onerror = function () { reject(new Error("sdk failed")); };
      document.head.appendChild(script);
    });
    return sdkPromise;
  }

  function showMapNote(box, text) {
    var note = box.querySelector(".map-note");
    if (note) { note.textContent = text + mapHelp(); note.hidden = false; }
  }

  // Kakao answers 401 unless the page's origin is registered for the key
  // (localhost and 127.0.0.1 count as different origins; file:// never works).
  // Say so on a developer's machine; visitors only see the short notice.
  function mapHelp() {
    var host = location.hostname;
    if (location.protocol === "file:") {
      return " 파일을 직접 열면 지도가 뜨지 않아요. python -m http.server 8765 --bind 127.0.0.1 -d site 로 띄운 뒤 http://127.0.0.1:8765 로 여세요.";
    }
    if (host === "localhost" || host === "127.0.0.1") {
      return " 카카오 개발자 콘솔의 플랫폼 > Web에 " + location.origin + " 이 등록돼 있는지 확인하세요.";
    }
    return "";
  }

  // --- home page ---------------------------------------------------------
  var board = document.querySelector("[data-board]");
  if (board) initBoard(board);

  function initBoard(board) {
    var rows = Array.prototype.slice.call(board.querySelectorAll(".job-row"));
    var state = { scope: "all", country: "", newcomer: false, demo: false, paid: false, saved: false, q: "", sort: "deadline" };

    function rowJob(row) {
      return {
        id: row.getAttribute("data-id"),
        scope: row.getAttribute("data-scope"),
        country: row.getAttribute("data-country") || "",
        region: row.getAttribute("data-region") || "",
        newcomer: row.getAttribute("data-newcomer") === "1",
        demo: row.getAttribute("data-demo") === "1",
        lat: parseFloat(row.getAttribute("data-lat")),
        lng: parseFloat(row.getAttribute("data-lng")),
        deadline: row.getAttribute("data-deadline"),
        // The highest hourly fee in won the notice names; 0 when it names none.
        rate: parseInt(row.getAttribute("data-rate"), 10) || 0,
        posted: row.getAttribute("data-posted") || "",
        name: row.getAttribute("data-name") || "",
        search: row.getAttribute("data-search") || "",
        row: row
      };
    }
    var jobs = rows.map(rowJob);
    // The build already lists jobs soonest deadline first.
    jobs.forEach(function (job, i) { job.order = i; });

    function matches(job) {
      return (state.scope === "all" || job.scope === state.scope) &&
        (!state.country || job.country === state.country) &&
        (!state.newcomer || job.newcomer) &&
        (!state.demo || job.demo) &&
        (!state.paid || job.rate > 0) &&
        (!state.saved || readStore("savedJobs").indexOf(job.id) !== -1) &&
        queryMatches(job);
    }

    // 시·도 이름으로 찾으면 글자가 아니라 근무지로 걸러요: '서울'에
    // 남서울대학교(천안)가 섞이지 않게요. 온라인·해외 공고는 빠져요.
    var REGION_FULL = {
      "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전라남도": "전남",
      "경상북도": "경북", "경상남도": "경남"
    };
    var REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
      "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
    function regionQuery(q) {
      var t = q.replace(/\s+/g, "");
      if (REGION_FULL[t]) return REGION_FULL[t];
      t = t.replace(/(특별자치시|특별자치도|특별시|광역시|시|도)$/, "");
      return REGIONS.indexOf(t) !== -1 ? t : "";
    }
    function queryMatches(job) {
      if (!state.q) return true;
      var region = regionQuery(state.q);
      if (region) return job.region === region;
      return job.search.indexOf(state.q) !== -1;
    }

    function hasPlace(job) { return !isNaN(job.lat) && !isNaN(job.lng); }

    function setHidden(selector, hidden) {
      var node = board.querySelector(selector);
      if (node) node.hidden = hidden;
    }

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    // Saved and applied marks live in this browser only (localStorage).
    function markRows() {
      var saved = readStore("savedJobs");
      var applied = readStore("appliedJobs");
      jobs.forEach(function (job) {
        var title = job.row.querySelector(".job-title");
        var marks = job.row.querySelector(".marks");
        if (!marks) {
          marks = document.createElement("span");
          marks.className = "marks";
          title.parentNode.insertBefore(marks, title);
        }
        marks.textContent = "";
        if (applied.indexOf(job.id) !== -1) marks.appendChild(el("span", "mark applied", "지원함"));
        if (saved.indexOf(job.id) !== -1) marks.appendChild(el("span", "mark", "저장됨"));
      });
      var count = board.querySelector("[data-saved-count]");
      if (count) count.textContent = saved.length ? String(saved.length) : "";
    }

    function apply() {
      var visible = jobs.filter(matches);
      jobs.forEach(function (job) { job.row.hidden = visible.indexOf(job) === -1; });
      if (open && open.row.hidden) collapse();
      board.querySelector("[data-count]").textContent = visible.length + "개";
      board.querySelector("[data-empty]").hidden = visible.length !== 0;
      markRows();
      setHidden("[data-saved-note]", !state.saved);
      var emptyTitle = board.querySelector("[data-empty-title]");
      var emptyDesc = board.querySelector("[data-empty-desc]");
      if (emptyTitle && emptyDesc) {
        if (!emptyDesc.hasAttribute("data-default")) {
          emptyDesc.setAttribute("data-default", emptyDesc.textContent);
          emptyTitle.setAttribute("data-default", emptyTitle.textContent);
        }
        emptyTitle.textContent = state.saved ? "저장한 공고가 아직 없어요" : emptyTitle.getAttribute("data-default");
        emptyDesc.textContent = state.saved
          ? "공고 상세에서 '저장'을 누르면 여기 모여요. 이 브라우저에만 남아요."
          : emptyDesc.getAttribute("data-default");
      }
      // The countries view exists only in the private build.
      setHidden("[data-view=countries]", state.scope !== "overseas");
      var summary = board.querySelector("[data-filter-summary]");
      if (summary) {
        var parts = [{ all: "전체", domestic: "국내", overseas: "해외", online: "온라인" }[state.scope]];
        if (state.country) parts.push(state.country);
        if (state.newcomer) parts.push("신입 가능");
        if (state.demo) parts.push("모의수업 있음");
        if (state.paid) parts.push("시급 나온 공고");
        if (state.saved) parts.push("저장한 공고");
        summary.textContent = parts.join(" · ");
      }
    }

    // --- opening a row ---------------------------------------------------
    // One row is open at a time. Its summary is already in the page, so
    // opening only unhides it. The map is a single Kakao map that moves into
    // whichever row asks for it.
    var open = null;
    var map = null;
    var mapEl = null;
    var pin = null;

    function collapse() {
      if (!open) return;
      open.row.querySelector(".row-detail").hidden = true;
      open.row.querySelector(".pick").setAttribute("aria-expanded", "false");
      open.row.removeAttribute("aria-current");
      var slot = open.row.querySelector("[data-row-map]");
      if (slot) slot.hidden = true;
      open = null;
    }

    function expand(job, withMap) {
      if (open !== job) {
        collapse();
        open = job;
        job.row.querySelector(".row-detail").hidden = false;
        job.row.querySelector(".pick").setAttribute("aria-expanded", "true");
        job.row.setAttribute("aria-current", "true");
      }
      if (withMap && hasPlace(job)) showMap(job);
      // Keep the opened row in view, without moving the page when it already is.
      var rect = job.row.getBoundingClientRect();
      if (rect.top < 0 || rect.bottom > window.innerHeight) {
        job.row.scrollIntoView({ behavior: "smooth", block: rect.height > window.innerHeight ? "start" : "nearest" });
      }
    }

    function showMap(job) {
      var slot = job.row.querySelector("[data-row-map]");
      if (!slot) return;
      slot.hidden = false;
      loadKakao().then(function () {
        if (open !== job) return;
        var pos = new kakao.maps.LatLng(job.lat, job.lng);
        if (!map) {
          mapEl = el("div", "row-map-canvas");
          slot.appendChild(mapEl);
          map = new kakao.maps.Map(mapEl, { center: pos, level: 5 });
          // On a phone the zoom bar covers half of this small map; pinch instead.
          if (!window.matchMedia("(max-width: 600px)").matches) {
            map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
          }
          // The row above already names the place, so the pin stays short.
          var tag = el("span", "pin", "근무지");
          tag.setAttribute("aria-pressed", "true");
          pin = new kakao.maps.CustomOverlay({ position: pos, content: tag, yAnchor: 1 });
          pin.setMap(map);
        } else if (mapEl.parentNode !== slot) {
          slot.appendChild(mapEl);
        }
        pin.setPosition(pos);
        map.relayout();
        map.setLevel(5);
        map.setCenter(pos);
      }).catch(function () {
        showMapNote(slot, "지도를 불러오지 못했어요.");
      });
    }

    rows.forEach(function (row, i) {
      var job = jobs[i];
      row.querySelector(".pick").addEventListener("click", function (ev) {
        // Ctrl/Cmd-click or a middle click still opens the job page in a new tab.
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) return;
        ev.preventDefault();
        if (open === job) collapse(); else expand(job, false);
      });
      var btn = row.querySelector("[data-map]");
      if (btn) btn.addEventListener("click", function () { expand(job, true); });
    });

    // --- sorting ---------------------------------------------------------
    var list = board.querySelector(".jobs");
    var sortNote = board.querySelector("[data-sort-note]");
    var sortSelect = board.querySelector("[data-sort-select]");
    // The visitor's position, asked for only when they pick 가까운순 and
    // kept in this page alone.
    var here = null;

    function km(a, b) {
      var rad = Math.PI / 180;
      var dLat = (b.lat - a.lat) * rad;
      var dLng = (b.lng - a.lng) * rad;
      var h = Math.pow(Math.sin(dLat / 2), 2) +
        Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.pow(Math.sin(dLng / 2), 2);
      return 12742 * Math.asin(Math.sqrt(h));
    }
    function distance(job) { return here && hasPlace(job) ? km(here, job) : Infinity; }
    // Ties (and online jobs, which have no place) fall back to the deadline order.
    var sorters = {
      deadline: function (a, b) { return a.order - b.order; },
      // Highest fee first; notices without one keep the deadline order at the end.
      pay: function (a, b) { return (b.rate - a.rate) || a.order - b.order; },
      newest: function (a, b) { return b.posted.localeCompare(a.posted) || b.id - a.id; },
      name: function (a, b) { return a.name.localeCompare(b.name, "ko") || a.order - b.order; },
      near: function (a, b) { return (distance(a) - distance(b)) || a.order - b.order; }
    };

    function sortNoteText(text) {
      if (!sortNote) return;
      sortNote.textContent = text || "";
      sortNote.hidden = !text;
    }

    function showDistances(on) {
      jobs.forEach(function (job) {
        var tag = job.row.querySelector(".dist");
        var d = on ? distance(job) : Infinity;
        if (d === Infinity) { if (tag) tag.parentNode.removeChild(tag); return; }
        if (!tag) {
          tag = el("span", "dist", "");
          var org = job.row.querySelector(".job-org");
          org.parentNode.insertBefore(tag, org.nextSibling);
        }
        tag.textContent = "내 위치에서 " + (d < 10 ? d.toFixed(1) : Math.round(d)) + "km";
      });
    }

    function sortBy(key) {
      state.sort = key;
      jobs.sort(sorters[key]);
      var ad = list.querySelector(".ad-slot");
      jobs.forEach(function (job) { list.appendChild(job.row); });
      if (ad && list.children[3]) list.insertBefore(ad, list.children[3]);
      if (sortSelect) sortSelect.value = key;
      showDistances(key === "near");
      if (key !== "near") sortNoteText("");
      // 가까운순 is not remembered, so a later visit never opens with a location prompt.
      try { localStorage.setItem("jobSort", key === "near" ? "deadline" : key); } catch (e) { /* not kept */ }
      apply();
    }

    function askHere(done) {
      if (here) { done(true); return; }
      if (!navigator.geolocation) { done(false, "이 브라우저는 위치 확인을 지원하지 않아요."); return; }
      // Browsers refuse location on plain http (other than localhost).
      if (window.isSecureContext === false) {
        done(false, "보안 연결이 아니라서 위치를 쓸 수 없어요. https://korean-job-helper.com 으로 열어 주세요.");
        return;
      }
      sortNoteText("내 위치를 확인하는 중이에요…");
      var deviceOff = "브라우저는 위치를 허용했지만 기기의 위치 서비스가 꺼져 있어요. " +
        "Windows는 설정 > 개인 정보 및 보안 > 위치, 휴대폰은 설정의 위치(GPS)를 켜고, 브라우저 앱에도 위치 권한을 준 뒤 다시 눌러 주세요.";
      navigator.geolocation.getCurrentPosition(function (pos) {
        here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        done(true);
      }, function (err) {
        if (err.code === 3) { done(false, "위치를 찾는 데 시간이 너무 걸렸어요. 잠시 뒤에 다시 눌러 주세요."); return; }
        if (err.code === 2) { done(false, deviceOff); return; }
        var blocked = "위치 권한이 꺼져 있어서 내 위치를 쓸 수 없어요. 주소창 옆 자물쇠 아이콘에서 위치를 허용해 주세요. " +
          "카카오톡·인스타그램 안에서 열었다면 Chrome이나 Safari로 열어 주세요.";
        // A refusal while the site itself is allowed comes from the device
        // (OS location off, or the browser app has no location access).
        if (!navigator.permissions || !navigator.permissions.query) { done(false, blocked); return; }
        navigator.permissions.query({ name: "geolocation" }).then(function (status) {
          done(false, status.state === "granted" ? deviceOff : blocked);
        }, function () { done(false, blocked); });
      }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 });
    }

    if (sortSelect) {
      sortSelect.addEventListener("change", function () {
        var key = sortSelect.value;
        if (key !== "near") { sortBy(key); return; }
        askHere(function (ok, why) {
          // Without a location the list keeps its order, so the menu goes back too.
          if (!ok) { sortSelect.value = state.sort; sortNoteText(why); return; }
          sortBy("near");
          sortNoteText("내 위치에서 가까운 순이에요. 위치는 이 화면에서만 쓰고 저장하지 않아요. 온라인 공고는 맨 뒤에 있어요.");
        });
      });
    }

    board.querySelectorAll("[data-scope-btn]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.scope = btn.getAttribute("data-scope-btn");
        setCountry("");
        board.querySelectorAll("[data-scope-btn]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        apply();
      });
    });
    // 나라별 카드: 누르면 그 나라 공고만, 같은 카드를 다시 누르면 해제.
    function setCountry(name) {
      state.country = name;
      board.querySelectorAll("[data-country-btn]").forEach(function (b) {
        b.setAttribute("aria-pressed", name && b.getAttribute("data-country-btn") === name ? "true" : "false");
      });
    }
    board.querySelectorAll("[data-country-btn]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-country-btn");
        setCountry(state.country === name ? "" : name);
        apply();
      });
    });
    board.querySelectorAll("[data-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-toggle");
        state[key] = !state[key];
        btn.setAttribute("aria-pressed", state[key] ? "true" : "false");
        apply();
      });
    });
    var search = board.querySelector("[data-search-input]");
    if (search) {
      // Some phone keyboards hold back the last 한글 syllable until composition
      // ends, so listen for that too; skip work when the query didn't change.
      var onSearch = function () {
        var q = search.value.trim().toLowerCase();
        if (q === state.q) return;
        state.q = q;
        apply();
      };
      search.addEventListener("input", onSearch);
      search.addEventListener("compositionend", onSearch);
      search.addEventListener("search", onSearch);
    }

    // Fetch the map script while the visitor reads the list, so the first
    // 지도보기 shows the map without waiting for it.
    if (jobs.some(hasPlace)) loadKakao().catch(function () { /* shown on 지도보기 */ });

    var lastSort = null;
    try { lastSort = localStorage.getItem("jobSort"); } catch (e) { lastSort = null; }
    if (list && lastSort && lastSort !== "deadline" && lastSort !== "near" && sorters[lastSort]) sortBy(lastSort);
    else apply();
    // Coming back from a job page (back button) must show what was saved there.
    window.addEventListener("pageshow", function (ev) { if (ev.persisted) apply(); });
  }

  // --- job page ----------------------------------------------------------
  var mini = document.querySelector("[data-mini-map]");
  if (mini) {
    var lat = parseFloat(mini.getAttribute("data-lat"));
    var lng = parseFloat(mini.getAttribute("data-lng"));
    loadKakao().then(function () {
      var pos = new kakao.maps.LatLng(lat, lng);
      var m = new kakao.maps.Map(mini, { center: pos, level: 5, draggable: true });
      var tag = document.createElement("span");
      tag.className = "pin";
      tag.setAttribute("aria-pressed", "true");
      tag.textContent = mini.getAttribute("data-label");
      new kakao.maps.CustomOverlay({ position: pos, content: tag, yAnchor: 1 }).setMap(m);
    }).catch(function () {
      showMapNote(mini, "지도를 불러오지 못했어요.");
    });
  }

  var copyBtn = document.querySelector("[data-copy]");
  if (copyBtn) {
    var copyStatus = document.querySelector("[data-copy-status]");
    var copyText = document.querySelector("[data-copy-text]").textContent.trim();
    var done = function (ok) {
      copyStatus.textContent = ok ? "복사했어요" : "주소를 길게 눌러 복사해 주세요";
      setTimeout(function () { copyStatus.textContent = ""; }, 2500);
    };
    copyBtn.addEventListener("click", function () {
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(copyText).then(function () { done(true); }, function () { done(false); });
        return;
      }
      // http:// previews have no Clipboard API; fall back to a hidden textarea.
      var area = document.createElement("textarea");
      area.value = copyText;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      document.body.removeChild(area);
      done(ok);
    });
  }

  // How many browsers saved each job is counted by serve.py. The browser is
  // known only by a random id made here, so nothing about the visitor is sent.
  function clientId() {
    try {
      var id = localStorage.getItem("cid");
      if (!id) {
        var bytes = new Uint8Array(16);
        if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
        else for (var i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
        id = Array.prototype.map.call(bytes, function (b) { return (b < 16 ? "0" : "") + b.toString(16); }).join("");
        localStorage.setItem("cid", id);
      }
      return id;
    } catch (e) { return null; }
  }
  function reportSave(id, on) {
    var cid = clientId();
    if (!cid || !window.fetch) return;
    // Under a plain static server (local preview) this just fails quietly.
    fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: id, client: cid, on: on }),
      keepalive: true
    }).catch(function () { /* not counted */ });
  }

  var jobId = document.body.getAttribute("data-job-id");
  var saveBtn = document.querySelector("[data-save]");
  if (jobId && saveBtn) {
    var paint = function (on) {
      saveBtn.setAttribute("aria-pressed", on ? "true" : "false");
      saveBtn.textContent = on ? "저장했어요 (이 브라우저)" : "저장";
    };
    paint(readStore("savedJobs").indexOf(jobId) !== -1);
    saveBtn.addEventListener("click", function () {
      var on = saveBtn.getAttribute("aria-pressed") !== "true";
      toggleStore("savedJobs", jobId, on);
      paint(on);
      reportSave(jobId, on);
    });
  }
  var appliedBtn = document.querySelector("[data-applied]");
  var appliedNote = document.querySelector("[data-applied-note]");
  if (jobId && appliedBtn && appliedNote) {
    if (readStore("appliedJobs").indexOf(jobId) !== -1) appliedNote.hidden = false;
    appliedBtn.addEventListener("click", function () {
      toggleStore("appliedJobs", jobId, true);
      appliedNote.hidden = false;
    });
  }

  // --- alert sign-up -----------------------------------------------------
  document.querySelectorAll("[data-alert-form]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var box = form.parentNode;
      var done = box.querySelector("[data-alert-done]");
      var email = form.querySelector("input[type=email]").value.trim();
      if (!email) return;
      // "alert" = new-job alerts; other kinds are service pre-registrations.
      var kind = form.getAttribute("data-kind") || "alert";
      if (!SITE.alertEndpoint) {
        done.textContent = "신청 접수는 곧 열려요. 그동안 이 페이지를 즐겨찾기 해 두세요.";
        done.hidden = false;
        return;
      }
      var summary = document.querySelector("[data-filter-summary]");
      fetch(SITE.alertEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: kind, email: email, filters: summary ? summary.textContent : "" })
      }).then(function (res) {
        if (!res.ok) throw new Error(res.status);
        form.hidden = true;
        done.textContent = kind === "alert"
          ? "알림을 켰어요. 새 공고가 올라오면 보내 드릴게요."
          : "신청됐어요. 서비스가 열리면 가장 먼저 알려 드릴게요.";
        done.hidden = false;
      }).catch(function () {
        done.textContent = "신청하지 못했어요. 잠시 뒤에 다시 해 주세요.";
        done.hidden = false;
      });
    });
  });

  // --- lesson-plan demo --------------------------------------------------
  var demo = document.querySelector("[data-demo-page]");
  if (demo) {
    var choice = { level: "초급 2", time: "15분" };
    demo.querySelectorAll("[data-opt]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var group = btn.getAttribute("data-opt");
        choice[group] = btn.textContent;
        demo.querySelectorAll('[data-opt="' + group + '"]').forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
      });
    });
    var left = 3;
    demo.querySelector("[data-generate]").addEventListener("click", function () {
      if (left > 0) left -= 1;
      demo.querySelector("[data-left]").textContent = String(left);
      demo.querySelector("[data-plan-heading]").textContent =
        choice.level + " · " + demo.querySelector("[data-topic]").value + " · " + choice.time;
      demo.querySelector("[data-waiting]").hidden = true;
      demo.querySelector("[data-result]").hidden = false;
    });
  }
})();

// Header dropdown (합격대비 코스, test build): click to open, click outside or
// Esc to close. Without this script the menu stays closed.
(function () {
  "use strict";
  var menus = document.querySelectorAll("[data-menu]");
  if (!menus.length) return;
  function close(menu) {
    menu.querySelector(".menu-btn").setAttribute("aria-expanded", "false");
    menu.querySelector(".menu-panel").hidden = true;
  }
  Array.prototype.forEach.call(menus, function (menu) {
    var btn = menu.querySelector(".menu-btn");
    // Links that jump within the same page leave no reload to close the menu.
    menu.querySelector(".menu-panel").addEventListener("click", function (event) {
      if (event.target.closest("a")) close(menu);
    });
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      Array.prototype.forEach.call(menus, close);
      if (!open) {
        btn.setAttribute("aria-expanded", "true");
        menu.querySelector(".menu-panel").hidden = false;
      }
    });
  });
  document.addEventListener("click", function (event) {
    Array.prototype.forEach.call(menus, function (menu) {
      if (!menu.contains(event.target)) close(menu);
    });
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    Array.prototype.forEach.call(menus, function (menu) {
      if (menu.querySelector(".menu-btn").getAttribute("aria-expanded") === "true") {
        close(menu);
        menu.querySelector(".menu-btn").focus();
      }
    });
  });
})();
