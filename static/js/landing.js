/*
 * Forsíðan (core/landing.html): skrollið stýrir skrefunum. Hlutinn er hár (CSS), sviðið er
 * „sticky“, og skrefið er smellipunkturinn (.lp-snap) sem er næst toppnum. Tréð fyllist upp í
 * data-count/data-total (CSS-umskipti á rect.fill) og talan telur upp eða niður.
 *
 * Með mús/snertifleti fer hver hreyfing eitt skref (hjólið er lesið hér). Á snertiskjám sjá
 * CSS-smellipunktar um það. Í fyrsta og síðasta skrefi skrollar síðan venjulega áfram.
 */
(() => {
  const section = document.querySelector(".lp-scroll");
  if (!section) return;
  const steps = [...section.querySelectorAll(".lp-step")];
  const total = Number(section.dataset.total) || 12;
  const fill = section.querySelector("rect.fill");
  const star = section.querySelector(".star");
  const num = section.querySelector(".lp-num");
  // Neðstu kúlurnar fyrst, svo þær poppa inn upp eftir trénu
  const ornaments = [...section.querySelectorAll("circle.orn")].sort(
    (a, b) => Number(b.getAttribute("cy")) - Number(a.getAttribute("cy")),
  );
  const win = section.querySelector(".lp-window");
  const rows = [...section.querySelectorAll(".lp-row")];
  const dots = [...section.querySelectorAll(".lp-dots button")];
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const TOP = 35;
  const BOTTOM = 245;

  const snaps = [...section.querySelectorAll(".lp-snap")];
  section.classList.add("is-live");
  document.documentElement.classList.add("lp-snapping");

  let current = -1;
  let shown = 0;
  let tween = 0;

  function countTo(target) {
    cancelAnimationFrame(tween);
    const from = shown;
    const start = performance.now();
    const ms = reduced ? 0 : 500;
    const tick = (now) => {
      const t = ms ? Math.min(1, (now - start) / ms) : 1;
      shown = Math.round(from + (target - from) * t);
      num.textContent = shown;
      if (t < 1) tween = requestAnimationFrame(tick);
    };
    tween = requestAnimationFrame(tick);
  }

  function setTree(count) {
    const y = BOTTOM - (BOTTOM - TOP) * (count / total);
    fill.setAttribute("y", y);
    fill.setAttribute("height", BOTTOM - y + 5);
    let delay = 0;
    for (const o of ornaments) {
      const on = Number(o.getAttribute("cy")) >= y;
      if (on && !o.classList.contains("on")) {
        // Ný kúla: poppar inn (stækkar og sest) með smá töf á eftir þeirri á undan
        o.style.transitionDelay = `${reduced ? 0 : 200 + delay}ms`;
        delay += 90;
        o.classList.add("on");
        setTimeout(() => o.classList.add("settled"), reduced ? 0 : 650 + delay);
      } else if (!on) {
        o.style.transitionDelay = "0ms";
        o.classList.remove("on", "settled");
      }
    }
    const full = count >= total;
    star.classList.toggle("lit", full);
    win.classList.toggle("complete", full);
  }

  function show(index) {
    if (index === current) return;
    current = index;
    steps.forEach((step, i) => {
      step.classList.toggle("on", i === index);
      step.toggleAttribute("inert", i !== index);
    });
    // Glugginn: s0–s4 segir CSS hvað sést (merki, listi, hugmyndir, deiling, peningar)
    steps.forEach((_, i) => win.classList.toggle(`s${i}`, i === index));
    for (const row of rows) row.classList.toggle("done", index >= Number(row.dataset.done));
    dots.forEach((dot, i) => dot.setAttribute("aria-current", i === index ? "step" : "false"));
    const count = Number(steps[index].dataset.count);
    setTree(count);
    countTo(count);
  }

  let queued = false;
  function update() {
    queued = false;
    // Toppur sviðsins (undir toppstikunni); skref breytist þegar skrollað er hálfa leið að næsta punkti
    const line = section.querySelector(".lp-stage").getBoundingClientRect().top;
    const gap = snaps.length > 1 ? snaps[1].offsetTop - snaps[0].offsetTop : 1;
    let index = 0;
    snaps.forEach((snap, i) => {
      if (snap.getBoundingClientRect().top <= line + gap / 2) index = i;
    });
    show(Math.min(steps.length - 1, index));
  }
  const schedule = () => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(update);
    }
  };

  const stage = section.querySelector(".lp-stage");
  // Hvar síðan á að standa svo smellipunktur i sé efst á (föstu) sviðinu, hvort sem það er fast eða ekki
  const stickyTop = () => parseFloat(getComputedStyle(stage).top) || 0;
  const scrollTopOf = (i) => window.scrollY + snaps[i].getBoundingClientRect().top - stickyTop();
  const pinned = () => {
    const rect = section.getBoundingClientRect();
    return rect.top <= stickyTop() + 2 && rect.bottom >= window.innerHeight - 2;
  };

  // Ein hreyfing = eitt skref: snertiflötur sendir marga atburði, svo beðið er þar til hlé verður
  let busy = false;
  let steppedAt = 0;
  let lastWheel = 0;
  section.addEventListener(
    "wheel",
    (event) => {
      if (event.ctrlKey || !event.deltaY) return;
      // Fyrir ofan (borðinn sést): fyrsta hakið niður fer beint í fyrsta skrefið
      if (!pinned()) {
        const above = section.getBoundingClientRect().top > stickyTop();
        if (above && event.deltaY > 0 && current === 0) {
          event.preventDefault();
          window.scrollTo({ top: scrollTopOf(0), behavior: reduced ? "auto" : "smooth" });
        }
        return;
      }
      const target = current + Math.sign(event.deltaY);
      if (target < 0 || target >= steps.length) return;
      event.preventDefault();
      const now = performance.now();
      const quiet = now - lastWheel > 160;
      lastWheel = now;
      if (busy && !(quiet && now - steppedAt > 450)) return;
      busy = true;
      steppedAt = now;
      show(target);
      window.scrollTo({ top: scrollTopOf(target), behavior: reduced ? "auto" : "smooth" });
    },
    { passive: false },
  );

  dots.forEach((dot, i) =>
    dot.addEventListener("click", () =>
      window.scrollTo({ top: scrollTopOf(i), behavior: reduced ? "auto" : "smooth" }),
    ),
  );

  window.addEventListener("scroll", schedule, { passive: true });
  window.addEventListener("resize", schedule);
  update();
})();
