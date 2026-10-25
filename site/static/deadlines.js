// Deadlines calculator: fills in the Date column from the dates entered.
// Dates are handled as UTC midnight so clock changes never shift a day.
(function () {
  var fmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  var DAY = 86400000;

  function parse(v) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || "");
    return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
  }

  // Calendar months: 31 January + 1 month is the last day of February.
  function addMonths(d, n) {
    var y = d.getUTCFullYear(), m = d.getUTCMonth() + n, day = d.getUTCDate();
    var last = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    return new Date(Date.UTC(y, m, Math.min(day, last)));
  }

  // offset: space-separated terms such as "6w", "-2w", "14d", "2m", "20w -15d"
  function shift(d, offset) {
    (offset || "").split(/\s+/).forEach(function (t) {
      var m = /^(-?\d+)([dwm])$/.exec(t);
      if (!m) return;
      var n = +m[1];
      d = m[2] === "m" ? addMonths(d, n) : new Date(d.getTime() + n * (m[2] === "w" ? 7 : 1) * DAY);
    });
    return d;
  }

  function today() {
    var t = new Date();
    return Date.UTC(t.getFullYear(), t.getMonth(), t.getDate());
  }

  function relative(d) {
    var days = Math.round((d.getTime() - today()) / DAY);
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    if (days === -1) return "yesterday";
    return days > 0 ? "in " + days + " days" : days * -1 + " days ago";
  }

  function update() {
    document.querySelectorAll("td.when[data-base]").forEach(function (cell) {
      var base = parse((document.getElementById(cell.dataset.base) || {}).value);
      var d = base && shift(base, cell.dataset.offset);
      var altBase = cell.dataset.altBase && parse((document.getElementById(cell.dataset.altBase) || {}).value);
      if (altBase) {
        var alt = shift(altBase, cell.dataset.altOffset);
        if (!d || alt > d) d = alt;
      }
      if (!d) {
        cell.textContent = "Enter a date";
        cell.classList.remove("set", "past");
        return;
      }
      cell.innerHTML = "";
      var strong = document.createElement("strong");
      strong.textContent = fmt.format(d);
      var rel = document.createElement("span");
      rel.className = "rel";
      rel.textContent = relative(d);
      cell.append(strong, document.createElement("br"), rel);
      cell.classList.add("set");
      cell.classList.toggle("past", d.getTime() < today());
    });
  }

  document.querySelectorAll("form[data-calc]").forEach(function (f) {
    f.addEventListener("input", update);
    f.addEventListener("change", update);
    f.addEventListener("submit", function (e) { e.preventDefault(); });
  });
  update();
})();
