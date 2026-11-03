/* 공감 페이지(start.html) scroll motion.
 *
 * Without this script every section is simply visible: the hidden start
 * states live under html.motion, which is set only here and only when the
 * visitor has not asked for reduced motion.
 *
 *  [data-reveal]        fades/slides in once it enters the screen; children
 *                       with --i stagger after it
 *  [data-count]         counts up from 0 to its value when revealed
 *  [data-scrub]         words light up one by one as the block scrolls past
 *  [data-progress]      a line that draws itself as its section scrolls by
 *  .start-bar           reading progress across the top of the page
 */
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) return;
  document.documentElement.classList.add("motion");

  // Reveal once.
  var seen = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      entry.target.classList.add("is-in");
      entry.target.querySelectorAll("[data-count]").forEach(count);
      if (entry.target.hasAttribute("data-count")) count(entry.target);
      seen.unobserve(entry.target);
    });
  }, { threshold: 0.18, rootMargin: "0px 0px -8% 0px" });
  document.querySelectorAll("[data-reveal]").forEach(function (el) { seen.observe(el); });

  function count(el) {
    if (el.dataset.counted) return;
    el.dataset.counted = "1";
    var target = parseFloat(el.getAttribute("data-count"));
    if (!isFinite(target)) return;
    var decimals = (el.getAttribute("data-count").split(".")[1] || "").length;
    var start = null, duration = 1400;
    function frame(now) {
      if (start === null) start = now;
      var t = Math.min(1, (now - start) / duration);
      var eased = 1 - Math.pow(1 - t, 4);
      el.textContent = (target * eased).toLocaleString("ko-KR", {
        minimumFractionDigits: decimals, maximumFractionDigits: decimals
      });
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  // Word-by-word scrub: split text into spans once.
  var scrubs = Array.prototype.map.call(document.querySelectorAll("[data-scrub]"), function (el) {
    var words = [];
    el.querySelectorAll("[data-words]").forEach(function (line) {
      var parts = line.textContent.split(/(\s+)/);
      line.textContent = "";
      parts.forEach(function (part) {
        if (/^\s+$/.test(part) || !part) { line.appendChild(document.createTextNode(part)); return; }
        var span = document.createElement("span");
        span.className = "w";
        span.textContent = part;
        line.appendChild(span);
        words.push(span);
      });
    });
    return { el: el, words: words };
  });
  var lines = document.querySelectorAll("[data-progress]");
  var bar = document.querySelector(".start-bar i");

  function progressOf(el, startAt, endAt) {
    // 0 when the block's top reaches startAt (fraction of viewport height),
    // 1 when its bottom reaches endAt.
    var r = el.getBoundingClientRect(), vh = window.innerHeight;
    var from = r.top - vh * startAt, span = r.height + vh * (startAt - endAt);
    return Math.max(0, Math.min(1, -from / (span || 1)));
  }

  var ticking = false;
  function update() {
    ticking = false;
    scrubs.forEach(function (s) {
      var p = progressOf(s.el, 0.75, 0.55);
      var lit = Math.round(p * s.words.length);
      s.words.forEach(function (w, i) { w.classList.toggle("on", i < lit); });
    });
    lines.forEach(function (el) {
      el.style.setProperty("--p", progressOf(el, 0.7, 0.5).toFixed(3));
    });
    if (bar) {
      var doc = document.documentElement;
      var max = doc.scrollHeight - window.innerHeight;
      bar.style.transform = "scaleX(" + (max > 0 ? window.scrollY / max : 0).toFixed(4) + ")";
    }
  }
  function onScroll() {
    if (!ticking) { ticking = true; requestAnimationFrame(update); }
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  update();
})();
