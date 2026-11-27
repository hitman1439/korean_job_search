// Home page: 목록 | 지도 switch on the home page, with one map of
// every posting the list currently shows (benchmarked on 잡아바 일자리맵).
// Runs after app.js, which owns the filters and row opening; this file only
// reads the rows (their data-* and hidden state) and clicks a row to open it.
(function () {
  "use strict";
  var section = document.querySelector("[data-all-map]");
  var board = document.querySelector("[data-board]");
  if (!section || !board) return;

  var SITE = window.SITE || {};
  var canvas = section.querySelector("[data-all-map-canvas]");
  var countEl = section.querySelector("[data-all-map-count]");
  var sheet = section.querySelector("[data-map-sheet]");
  var sheetTitle = sheet.querySelector("[data-sheet-title]");
  var sheetList = sheet.querySelector("[data-sheet-list]");
  var list = board.querySelector(".list-panel");
  var rows = Array.prototype.slice.call(board.querySelectorAll(".job-row"));
  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-view-btn]"));

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function text(row, sel) {
    var node = row.querySelector(sel);
    return node ? node.textContent.trim() : "";
  }

  // --- Kakao SDK: reuse the script app.js already asked for ----------------
  var sdk = null;
  function loadKakao() {
    if (sdk) return sdk;
    sdk = new Promise(function (resolve, reject) {
      if (!SITE.kakaoKey) { reject(new Error("no key")); return; }
      var done = function () { window.kakao.maps.load(resolve); };
      if (window.kakao && window.kakao.maps && window.kakao.maps.load) { done(); return; }
      var script = document.querySelector('script[src*="dapi.kakao.com"]');
      if (!script) {
        script = document.createElement("script");
        script.src = "https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&libraries=clusterer&appkey=" + encodeURIComponent(SITE.kakaoKey);
        document.head.appendChild(script);
      }
      script.addEventListener("load", function () {
        if (window.kakao && window.kakao.maps) done(); else reject(new Error("sdk refused"));
      });
      script.addEventListener("error", function () { reject(new Error("sdk failed")); });
      // app.js's script may have finished (or failed) before this listened.
      setTimeout(function () {
        if (window.kakao && window.kakao.maps && window.kakao.maps.load) done();
        else reject(new Error("sdk timeout"));
      }, 8000);
    });
    return sdk;
  }

  // --- view switch --------------------------------------------------------
  var view = "list";
  function setView(next) {
    view = next;
    document.body.classList.toggle("view-map", next === "map");
    tabs.forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-view-btn") === next)); });
    section.hidden = next !== "map";
    if (list) list.hidden = next === "map";
    if (next === "map") {
      draw();
      // Phones: bring the tabs to the top so the map fills the screen under them.
      if (window.matchMedia("(max-width: 600px)").matches && tabs[0]) {
        window.scrollTo(0, tabs[0].parentNode.getBoundingClientRect().top + window.pageYOffset - 8);
      }
    } else closeSheet();
  }
  tabs.forEach(function (b) {
    b.addEventListener("click", function () { setView(b.getAttribute("data-view-btn")); });
  });

  // --- the map ------------------------------------------------------------
  var map = null;
  var clusterer = null;
  var hereDot = null;
  var byOverlay = [];   // [overlay, row] pairs, to find rows from a cluster
  var drawnKey = "";

  function placed(row) {
    return !row.hidden && row.getAttribute("data-lat") !== "" && row.getAttribute("data-lng") !== "";
  }
  function urgent(row) {
    var badge = row.querySelector(".badge.urgent");
    return !!badge;
  }

  function draw() {
    var shown = rows.filter(function (r) { return !r.hidden; });
    var onMap = shown.filter(placed);
    var off = shown.length - onMap.length;
    // Filters picked in the list still apply on the map, even while hidden.
    var filtered = rows.some(function (r) { return r.hidden; });
    countEl.textContent = onMap.length
      ? "지도에 " + onMap.length + "개" + (filtered ? " · 목록 조건 적용 중" : off ? " · 온라인·해외 " + off + "개는 목록에서" : "")
      : "지금 조건에서 지도에 표시할 국내 공고가 없어요";
    loadKakao().then(function () {
      if (!map) {
        map = new kakao.maps.Map(canvas, { center: new kakao.maps.LatLng(36.4, 127.8), level: 13 });
        clusterer = new kakao.maps.MarkerClusterer({
          map: map, averageCenter: true, minLevel: 1, minClusterSize: 2, gridSize: 56,
          disableClickZoom: true,
          styles: [{
            width: "44px", height: "44px", lineHeight: "38px", textAlign: "center",
            background: "#1a55c0", color: "#fff", fontSize: "16px", fontWeight: "700",
            borderRadius: "50%", border: "3px solid #fff", boxShadow: "0 2px 8px rgba(0,0,0,.25)"
          }]
        });
        kakao.maps.event.addListener(clusterer, "clusterclick", function (cluster) {
          var picked = cluster.getMarkers();
          openSheet(byOverlay.filter(function (p) { return picked.indexOf(p[0]) !== -1; })
            .map(function (p) { return p[1]; }));
        });
        kakao.maps.event.addListener(map, "click", closeSheet);
      }
      map.relayout();
      var key = onMap.map(function (r) { return r.getAttribute("data-id"); }).join(",");
      if (key === drawnKey) return;
      drawnKey = key;
      closeSheet();
      clusterer.clear();
      byOverlay = [];
      var bounds = new kakao.maps.LatLngBounds();
      var overlays = onMap.map(function (row) {
        var pos = new kakao.maps.LatLng(parseFloat(row.getAttribute("data-lat")), parseFloat(row.getAttribute("data-lng")));
        bounds.extend(pos);
        var dot = el("button", "map-dot" + (urgent(row) ? " urgent" : ""), "1");
        dot.type = "button";
        dot.setAttribute("aria-label", row.getAttribute("data-title") + " 위치");
        dot.addEventListener("click", function (ev) { ev.stopPropagation(); openSheet([row]); });
        var ov = new kakao.maps.CustomOverlay({ position: pos, content: dot, yAnchor: 0.5, clickable: true });
        byOverlay.push([ov, row]);
        return ov;
      });
      clusterer.addMarkers(overlays);
      if (overlays.length === 1) { map.setLevel(6); map.setCenter(bounds.getSouthWest()); }
      else if (overlays.length) map.setBounds(bounds, 60, 40, 120, 40);
    }).catch(function () {
      var note = section.querySelector(".map-note");
      note.textContent = "지도를 불러오지 못했어요.";
      note.hidden = false;
    });
  }

  // Filters and search hide rows in app.js; redraw when the map is showing.
  var pending = null;
  new MutationObserver(function () {
    if (view !== "map") return;
    clearTimeout(pending);
    pending = setTimeout(draw, 50);
  }).observe(board.querySelector(".jobs"), { attributes: true, subtree: true, attributeFilter: ["hidden"] });

  // --- bottom sheet ---------------------------------------------------------
  function openSheet(picked) {
    sheetList.textContent = "";
    sheetTitle.textContent = "공고 " + picked.length + "건";
    picked.forEach(function (row) {
      var li = el("li");
      var btn = el("button", "sheet-item");
      btn.type = "button";
      var top = el("span", "sheet-top");
      var badge = text(row, ".badge-meta");
      if (badge) top.appendChild(el("span", "sheet-badge" + (urgent(row) ? " urgent" : ""), badge));
      var pay = text(row, ".meta-pay");
      if (pay) top.appendChild(el("span", "sheet-pay", pay));
      if (top.childNodes.length) btn.appendChild(top);
      btn.appendChild(el("span", "sheet-title", row.getAttribute("data-title")));
      btn.appendChild(el("span", "sheet-org", row.getAttribute("data-org")));
      btn.addEventListener("click", function () { openRow(row); });
      li.appendChild(btn);
      sheetList.appendChild(li);
    });
    sheet.hidden = false;
    sheetList.scrollTop = 0;
  }
  function closeSheet() { sheet.hidden = true; }
  sheet.querySelector("[data-sheet-close]").addEventListener("click", closeSheet);

  // A sheet item opens that posting's card in the list (app.js does the opening).
  function openRow(row) {
    setView("list");
    var pick = row.querySelector(".pick");
    if (pick && pick.getAttribute("aria-expanded") !== "true") pick.click();
    row.scrollIntoView({ block: "start" });
  }

  // --- my location: asked only when the button is pressed, never kept -------
  section.querySelector("[data-all-map-here]").addEventListener("click", function () {
    if (!navigator.geolocation) { countEl.textContent = "이 브라우저는 위치를 알려 주지 않아요"; return; }
    navigator.geolocation.getCurrentPosition(function (p) {
      loadKakao().then(function () {
        var pos = new kakao.maps.LatLng(p.coords.latitude, p.coords.longitude);
        if (!hereDot) hereDot = new kakao.maps.CustomOverlay({ position: pos, content: el("span", "here-dot"), yAnchor: 0.5 });
        hereDot.setPosition(pos);
        hereDot.setMap(map);
        map.setLevel(8);
        map.setCenter(pos);
      });
    }, function () {
      countEl.textContent = "위치를 확인하지 못했어요. 브라우저의 위치 권한을 확인해 주세요";
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 });
  });
})();
