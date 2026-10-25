// Hover/focus tooltips for chart points and ranked bars. Charts work without it.
(function () {
  var tip = document.getElementById("tip");
  if (!tip) return;
  function show(e) {
    var t = e.target.closest("[data-tip]");
    if (!t) return;
    tip.textContent = t.getAttribute("data-tip");
    tip.hidden = false;
    var r = t.getBoundingClientRect();
    var x = r.left + r.width / 2 + window.scrollX;
    var y = r.top + window.scrollY - 8;
    tip.style.left = Math.max(8, Math.min(x - tip.offsetWidth / 2, document.documentElement.clientWidth - tip.offsetWidth - 8)) + "px";
    tip.style.top = (y - tip.offsetHeight) + "px";
  }
  function hide(e) {
    if (e.target.closest && e.target.closest("[data-tip]")) tip.hidden = true;
  }
  document.addEventListener("mouseover", show);
  document.addEventListener("mouseout", hide);
  document.addEventListener("focusin", show);
  document.addEventListener("focusout", hide);
  // Strip native <title> tooltips once the custom one is active, to avoid doubles.
  document.querySelectorAll("[data-tip] > title").forEach(function (n) { n.remove(); });
  document.querySelectorAll("li[data-tip]").forEach(function (n) { n.removeAttribute("title"); n.tabIndex = 0; });
})();

// Tables that scroll sideways get a tab stop and a name, so keyboard users can scroll them.
(function () {
  // Name it after its caption, its figure's title, or the nearest heading above it.
  function name(w) {
    var cap = w.querySelector("caption");
    if (cap) return cap.textContent.trim();
    var fig = w.closest("figure");
    var h = fig && (fig.querySelector("h3") || fig.querySelector("figcaption"));
    if (h) return h.textContent.trim();
    var all = document.querySelectorAll("h1, h2, h3"), last = null;
    for (var i = 0; i < all.length; i++) {
      if (all[i].compareDocumentPosition(w) & Node.DOCUMENT_POSITION_FOLLOWING) last = all[i];
    }
    return last ? last.textContent.trim() : "Data";
  }
  function mark() {
    document.querySelectorAll(".tablewrap").forEach(function (w) {
      if (w.scrollWidth > w.clientWidth + 1) {
        if (!w.hasAttribute("tabindex")) {
          w.tabIndex = 0;
          w.setAttribute("role", "region");
          w.setAttribute("aria-label", name(w) + ", table, scrolls sideways");
        }
      } else if (w.getAttribute("role") === "region" && document.activeElement !== w) {
        w.removeAttribute("tabindex"); w.removeAttribute("role"); w.removeAttribute("aria-label");
      }
    });
  }
  mark();
  window.addEventListener("resize", mark);
  document.addEventListener("toggle", mark, true);
})();
