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
    el.className = "badge" + (b.cls ? " " + b.cls : "");
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
    var state = { scope: "all", newcomer: false, demo: false, saved: false, q: "", selected: null, sort: "deadline" };
    var map = null;
    var clusterer = null;
    var overlays = {};
    var popup = null;
    var mapBox = board.querySelector(".map-box");

    function rowJob(row) {
      return {
        id: row.getAttribute("data-id"),
        scope: row.getAttribute("data-scope"),
        newcomer: row.getAttribute("data-newcomer") === "1",
        demo: row.getAttribute("data-demo") === "1",
        lat: parseFloat(row.getAttribute("data-lat")),
        lng: parseFloat(row.getAttribute("data-lng")),
        deadline: row.getAttribute("data-deadline"),
        posted: row.getAttribute("data-posted") || "",
        name: row.getAttribute("data-name") || "",
        search: row.getAttribute("data-search") || "",
        title: row.getAttribute("data-title"),
        org: row.getAttribute("data-org"),
        url: row.querySelector(".go").getAttribute("href"),
        chips: Array.prototype.map.call(row.querySelectorAll(".chip"), function (c) { return c.textContent; }),
        row: row
      };
    }
    var jobs = rows.map(rowJob);
    // The build already lists jobs soonest deadline first.
    jobs.forEach(function (job, i) { job.order = i; });

    function matches(job) {
      return (state.scope === "all" || job.scope === state.scope) &&
        (!state.newcomer || job.newcomer) &&
        (!state.demo || job.demo) &&
        (!state.saved || readStore("savedJobs").indexOf(job.id) !== -1) &&
        (!state.q || job.search.indexOf(state.q) !== -1);
    }

    function hasPlace(job) { return !isNaN(job.lat) && !isNaN(job.lng); }

    function setHidden(selector, hidden) {
      var el = board.querySelector(selector);
      if (el) el.hidden = hidden;
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
      if (popup) closePopup();
      var visible = jobs.filter(matches);
      jobs.forEach(function (job) { job.row.hidden = visible.indexOf(job) === -1; });
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

      var showMap = state.scope === "all" || state.scope === "domestic";
      // The countries view exists only in the private build.
      setHidden("[data-view=map]", !showMap);
      setHidden("[data-view=countries]", state.scope !== "overseas");
      setHidden("[data-view=online]", state.scope !== "online");

      var current = visible.filter(function (j) { return j.id === state.selected && hasPlace(j); })[0];
      if (!current) current = visible.filter(hasPlace)[0] || null;
      select(current ? current.id : null, false);

      if (map) {
        var bounds = new kakao.maps.LatLngBounds();
        var shown = [];
        jobs.forEach(function (job) {
          var overlay = overlays[job.id];
          if (overlay && showMap && visible.indexOf(job) !== -1) {
            shown.push(overlay);
            bounds.extend(overlay.getPosition());
          }
        });
        // Pins close together (several boards in Seoul) merge into one count bubble.
        clusterer.clear();
        clusterer.addMarkers(shown);
        if (showMap) { map.relayout(); if (shown.length) map.setBounds(bounds, 60, 60, 160, 60); }
      }
      var summary = board.querySelector("[data-filter-summary]");
      if (summary) {
        var parts = [{ all: "전체", domestic: "국내", overseas: "해외", online: "온라인" }[state.scope]];
        if (state.newcomer) parts.push("신입 가능");
        if (state.demo) parts.push("모의수업 있음");
        if (state.saved) parts.push("저장한 공고");
        summary.textContent = parts.join(" · ");
      }
    }

    function select(id, pan) {
      state.selected = id;
      var chosen = null;
      jobs.forEach(function (job) {
        var on = job.id === id;
        if (on) chosen = job;
        if (on) job.row.setAttribute("aria-current", "true"); else job.row.removeAttribute("aria-current");
        var pin = overlays[job.id] && overlays[job.id].getContent();
        if (pin) pin.setAttribute("aria-pressed", on ? "true" : "false");
        if (overlays[job.id]) overlays[job.id].setZIndex(on ? 3 : 1);
      });
      if (!pan || !chosen || !map || !overlays[chosen.id]) return;
      // Picked from the list: show its bubble, zooming in first if the pin
      // is folded into a count bubble.
      var pos = overlays[chosen.id].getPosition();
      if (!overlays[chosen.id].getMap()) map.setLevel(Math.min(map.getLevel(), 4), { anchor: pos });
      map.panTo(pos);
      jobPopup(chosen);
    }

    // Speech bubble over the map: one job for a pin, a list for a count bubble.
    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }
    function closePopup() {
      if (popup) { popup.setMap(null); popup = null; }
    }
    // Any press outside the bubble closes it: the map, a pin, the list, the
    // page. A pin or count bubble then opens its own bubble on the click.
    var downAt = null;
    document.addEventListener("pointerdown", function (ev) {
      downAt = { x: ev.clientX, y: ev.clientY };
      if (popup && !popup.getContent().contains(ev.target)) closePopup();
    }, true);
    // Pins and count bubbles let drags through to the map, so a click that
    // ends a drag must not open anything.
    function isTap(ev) {
      return !downAt || Math.abs(ev.clientX - downAt.x) + Math.abs(ev.clientY - downAt.y) < 8;
    }
    function openPopup(position, content) {
      closePopup();
      var box = el("div", "map-pop");
      box.setAttribute("role", "dialog");
      var x = el("button", "x", "×");
      x.type = "button";
      x.setAttribute("aria-label", "닫기");
      x.addEventListener("click", closePopup);
      box.appendChild(x);
      box.appendChild(content);
      // Clicks and drags inside the bubble must not reach the map.
      ["mousedown", "touchstart", "click", "dblclick", "wheel"].forEach(function (type) {
        box.addEventListener(type, function (ev) { ev.stopPropagation(); });
      });
      popup = new kakao.maps.CustomOverlay({ position: position, content: box, yAnchor: 0, zIndex: 10, clickable: true });
      popup.setMap(map);
      // Move the map so the whole bubble is inside it, not cut at an edge.
      requestAnimationFrame(function () {
        var frame = mapBox.getBoundingClientRect();
        var rect = box.getBoundingClientRect();
        var pad = 16;
        var dx = 0, dy = 0;
        if (rect.top < frame.top + pad) dy = rect.top - frame.top - pad;
        else if (rect.bottom > frame.bottom - pad) dy = rect.bottom - frame.bottom + pad;
        if (rect.left < frame.left + pad) dx = rect.left - frame.left - pad;
        else if (rect.right > frame.right - pad) dx = rect.right - frame.right + pad;
        if (dx || dy) map.panBy(dx, dy);
      });
    }
    function badgeEl(job) {
      var b = badgeFor(job.deadline);
      return el("span", "badge" + (b.cls ? " " + b.cls : ""), b.text);
    }
    function jobPopup(job) {
      var frag = document.createDocumentFragment();
      frag.appendChild(badgeEl(job));
      frag.appendChild(el("p", "t", job.title));
      frag.appendChild(el("p", "o", job.org));
      if (job.chips.length) {
        var chips = el("div", "chips");
        job.chips.forEach(function (c) { chips.appendChild(el("span", "chip", c)); });
        frag.appendChild(chips);
      }
      var go = el("a", "btn btn-primary", "자세히 보기");
      go.href = job.url;
      frag.appendChild(go);
      openPopup(overlays[job.id].getPosition(), frag);
    }
    function clusterPopup(cluster) {
      var markers = cluster.getMarkers();
      var inside = jobs.filter(function (job) { return markers.indexOf(overlays[job.id]) !== -1; });
      var frag = document.createDocumentFragment();
      frag.appendChild(el("p", "head", "같은 곳의 공고 " + inside.length + "개"));
      var list = el("ul");
      inside.forEach(function (job) {
        var li = el("li");
        var grow = el("div", "grow");
        grow.appendChild(badgeEl(job));
        grow.appendChild(el("p", "t", job.title));
        grow.appendChild(el("p", "o", job.org));
        var go = el("a", "go", "자세히");
        go.href = job.url;
        li.appendChild(grow);
        li.appendChild(go);
        list.appendChild(li);
      });
      frag.appendChild(list);
      openPopup(cluster.getCenter(), frag);
    }

    // --- sorting ---------------------------------------------------------
    var list = board.querySelector(".jobs");
    var sortNote = board.querySelector("[data-sort-note]");
    // The visitor's position, asked for only when they pick 가까운순 and
    // kept in this page alone.
    var here = null;
    var hereDot = null;

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

    function showHere() {
      if (!map || !here || hereDot) return;
      var dot = el("span", "here-dot", "");
      dot.setAttribute("aria-label", "내 위치");
      hereDot = new kakao.maps.CustomOverlay({
        position: new kakao.maps.LatLng(here.lat, here.lng), content: dot, zIndex: 2, clickable: false
      });
      hereDot.setMap(map);
    }

    function sortBy(key) {
      state.sort = key;
      jobs.sort(sorters[key]);
      var ad = list.querySelector(".ad-slot");
      jobs.forEach(function (job) { list.appendChild(job.row); });
      if (ad && list.children[3]) list.insertBefore(ad, list.children[3]);
      board.querySelectorAll("[data-sort]").forEach(function (b) {
        b.setAttribute("aria-pressed", b.getAttribute("data-sort") === key ? "true" : "false");
      });
      showDistances(key === "near");
      if (key !== "near") sortNoteText("");
      // 가까운순 is not remembered, so a later visit never opens with a location prompt.
      try { localStorage.setItem("jobSort", key === "near" ? "deadline" : key); } catch (e) { /* not kept */ }
      list.scrollTop = 0;
      apply();
    }

    // say() shows progress where the visitor clicked (list or map).
    function askHere(done, say) {
      if (here) { done(true); return; }
      if (!navigator.geolocation) { done(false, "이 브라우저는 위치 확인을 지원하지 않아요."); return; }
      // Browsers refuse location on plain http (other than localhost).
      if (window.isSecureContext === false) {
        done(false, "보안 연결이 아니라서 위치를 쓸 수 없어요. https://korean-job-helper.com 으로 열어 주세요.");
        return;
      }
      (say || sortNoteText)("내 위치를 확인하는 중이에요…");
      var deviceOff = "브라우저는 위치를 허용했지만 기기의 위치 서비스가 꺼져 있어요. " +
        "Windows는 설정 > 개인 정보 및 보안 > 위치, 휴대폰은 설정의 위치(GPS)를 켜고, 브라우저 앱에도 위치 권한을 준 뒤 다시 눌러 주세요.";
      navigator.geolocation.getCurrentPosition(function (pos) {
        here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        showHere();
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

    // "내 위치" on the map: mark the visitor and zoom in around them.
    var hereNote = null;
    function hereNoteText(text) {
      if (!hereNote) return;
      hereNote.textContent = text || "";
      hereNote.hidden = !text;
    }
    function addHereButton() {
      var btn = el("button", "here-btn", "내 위치");
      btn.type = "button";
      hereNote = el("p", "here-note", "");
      hereNote.setAttribute("role", "status");
      hereNote.hidden = true;
      btn.addEventListener("click", function () {
        btn.disabled = true;
        askHere(function (ok, why) {
          btn.disabled = false;
          if (!ok) { hereNoteText(why); return; }
          hereNoteText("");
          closePopup();
          var pos = new kakao.maps.LatLng(here.lat, here.lng);
          if (map.getLevel() > 6) map.setLevel(6, { anchor: pos });
          map.panTo(pos);
        }, hereNoteText);
      });
      mapBox.appendChild(hereNote);
      mapBox.appendChild(btn);
    }

    board.querySelectorAll("[data-sort]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.getAttribute("data-sort");
        if (key !== "near") { sortBy(key); return; }
        askHere(function (ok, why) {
          if (!ok) { sortNoteText(why); return; }
          sortBy("near");
          sortNoteText("내 위치에서 가까운 순이에요. 위치는 이 화면에서만 쓰고 저장하지 않아요. 온라인 공고는 맨 뒤에 있어요.");
        });
      });
    });

    board.querySelectorAll("[data-scope-btn]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.scope = btn.getAttribute("data-scope-btn");
        board.querySelectorAll("[data-scope-btn]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
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
      search.addEventListener("input", function () {
        state.q = search.value.trim().toLowerCase();
        apply();
      });
    }
    rows.forEach(function (row) {
      row.querySelector(".pick").addEventListener("click", function () {
        select(row.getAttribute("data-id"), true);
        if (window.matchMedia("(max-width: 900px)").matches && mapBox) {
          mapBox.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    });

    var placed = jobs.filter(hasPlace);
    if (mapBox && placed.length) {
      loadKakao().then(function () {
        map = new kakao.maps.Map(document.getElementById("map"), {
          center: new kakao.maps.LatLng(placed[0].lat, placed[0].lng),
          level: 9
        });
        map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
        clusterer = new kakao.maps.MarkerClusterer({
          map: map,
          averageCenter: true,
          minLevel: 1,
          disableClickZoom: true,
          // Not clickable, so a drag that starts on a count bubble still pans
          // the map; taps are handled on the bubble's element below.
          clickable: false,
          gridSize: 56,
          styles: [{
            width: "48px", height: "48px", lineHeight: "48px", borderRadius: "24px",
            background: "#191f28", color: "#ffffff", textAlign: "center",
            fontSize: "15px", fontWeight: "600", boxShadow: "0 2px 8px rgba(0,0,0,0.25)"
          }]
        });
        placed.forEach(function (job) {
          var pin = document.createElement("button");
          pin.type = "button";
          pin.className = "pin" + (badgeFor(job.deadline).cls === "urgent" ? " urgent" : "");
          pin.textContent = pinText(job.deadline);
          pin.setAttribute("aria-label", job.org + ", " + badgeFor(job.deadline).text);
          pin.setAttribute("aria-pressed", "false");
          pin.addEventListener("click", function (ev) {
            if (!isTap(ev)) return;
            select(job.id, false);
            jobPopup(job);
          });
          overlays[job.id] = new kakao.maps.CustomOverlay({
            position: new kakao.maps.LatLng(job.lat, job.lng),
            content: pin,
            yAnchor: 1,
            clickable: false
          });
        });
        showHere();
        addHereButton();
        // A count bubble zooms in until its jobs separate into single pins.
        // Jobs at the very same spot never separate, so those get the list.
        function onCluster(cluster) {
          closePopup();
          var markers = cluster.getMarkers();
          var first = markers[0].getPosition();
          var samePlace = markers.every(function (m) {
            var pos = m.getPosition();
            return Math.abs(pos.getLat() - first.getLat()) < 1e-5 && Math.abs(pos.getLng() - first.getLng()) < 1e-5;
          });
          if (samePlace || map.getLevel() <= 1) { clusterPopup(cluster); return; }
          var bounds = new kakao.maps.LatLngBounds();
          markers.forEach(function (m) { bounds.extend(m.getPosition()); });
          map.setBounds(bounds, 80, 80, 80, 80);
        }
        kakao.maps.event.addListener(clusterer, "clustered", function (clusters) {
          clusters.forEach(function (cluster) {
            var node = cluster.getClusterMarker().getContent();
            if (!node || !node.addEventListener) return;
            node.kjCluster = cluster;
            if (node.kjWired) return;
            node.kjWired = true;
            node.style.cursor = "pointer";
            node.addEventListener("click", function (ev) {
              if (isTap(ev)) onCluster(node.kjCluster);
            });
          });
        });
        mapBox.querySelector(".map-note").hidden = true;
        apply();
      }).catch(function () {
        showMapNote(mapBox, "지도를 불러오지 못했어요. 오른쪽 목록에서 공고를 확인해 주세요.");
      });
    } else if (mapBox) {
      showMapNote(mapBox, "지도에 표시할 국내 공고가 아직 없어요.");
    }
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
