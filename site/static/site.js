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
