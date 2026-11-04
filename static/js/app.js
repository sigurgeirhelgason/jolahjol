/*
 * Alpine-íhlutir. CSP-útgáfa Alpine leyfir ekki inline-segðir („open = !open“), svo öll
 * hegðun er skilgreind hér og sniðmátin vísa bara í nöfn eiginleika og aðferða.
 * Þessi skrá verður að hlaðast á undan Alpine (báðar með defer, í þessari röð).
 */

// Elkó/Elko/ELKO → „elko“; sama regla og apps.core.text.fold_key
const foldKey = (s) => (s || "").trim().toLocaleLowerCase("is").normalize("NFD").replace(/[̀-ͯ]/g, "");

document.addEventListener("alpine:init", () => {
  // Fellivalmynd: hnappur + spjald, lokast við smell utan, Escape eða val
  Alpine.data("menu", () => ({
    open: false,
    toggle() { this.open = !this.open; },
    close() { this.open = false; },
  }));

  // Afrita texta (t.d. boðshlekk) á klippiborð
  Alpine.data("copy", () => ({
    copied: false,
    get label() { return this.copied ? this.$el.dataset.done : this.$el.dataset.label; },
    async copy() {
      const text = this.$refs.source.value;
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        this.$refs.source.select();
        document.execCommand("copy");
      }
      this.copied = true;
      setTimeout(() => { this.copied = false; }, 2000);
    },
  }));

  // Staðfesting á hættulegum aðgerðum: <form x-data="confirm" data-message="…" x-on:submit="ask">
  Alpine.data("confirm", () => ({
    ask(event) {
      if (!window.confirm(this.$el.dataset.message)) event.preventDefault();
    },
  }));

  // Ársval: <select> þar sem gildi hvers valkosts er slóð
  Alpine.data("navSelect", () => ({
    go(event) { window.location.href = event.target.value; },
  }));

  // Upphæðareitur í línu: sýnir „15.000 kr.“ en hráa tölu á meðan breytt er (svo +2000 virki)
  Alpine.data("amountCell", () => ({
    showRaw() {
      this.$el.value = this.$el.dataset.raw;
      this.$el.select();
    },
    commit() { this.$el.blur(); },
  }));

  // „+ Hugmynd“: Enter eða komma vistar, líka ef farið er úr reitnum með texta í honum
  Alpine.data("chipInput", () => ({
    onKey(event) {
      if (event.key !== "Enter" && event.key !== ",") return;
      event.preventDefault();
      this.send();
    },
    onBlur() { this.send(); },
    send() {
      if (this.$el.value.trim()) htmx.trigger(this.$el, "add");
    },
  }));

  // Gluggi (<dialog>) sem htmx fyllir; opnast þegar efni kemur og lokast við „closeModal“
  Alpine.data("modal", () => ({
    init() {
      this.$el.addEventListener("click", (event) => {
        if (event.target.closest("[data-close]") || event.target === this.$el) this.$el.close();
      });
    },
    cleanup() { document.getElementById("modal-body").innerHTML = ""; },
  }));

  // Skilaboð neðst (t.d. „Gjöf eytt“ með Afturkalla) sem hverfa eftir 6 sekúndur
  Alpine.data("toast", () => ({
    init() {
      setTimeout(() => this.$el.classList.remove("show"), 6000);
    },
  }));

  // Hugmyndaglugginn: gefendur (merki + tillögur), keypt fyrir annan, hlutir, hlekkur og búð
  Alpine.data("ideaForm", () => ({
    tags: [],
    active: -1,
    seq: 0,
    timer: null,
    forOther: false,
    link: "",
    storeLocations: {},

    init() {
      this.tags = JSON.parse(this.$el.dataset.givers || "[]").map((t) => ({ name: t.name, share: t.share ?? "" }));
      this.storeLocations = JSON.parse(this.$el.dataset.storeLocations || "{}");
      this.forOther = this.$refs.other.checked;
      this.link = this.$refs.link.value;
    },

    get hasGivers() { return this.tags.length > 0; },
    get showPaid() { return this.forOther && this.hasGivers; },
    get showShares() { return this.forOther && this.tags.length > 1; },
    get hasLink() { return /^https?:\/\//i.test(this.link); },

    focusInput(event) {
      if (event.target === event.currentTarget) this.$refs.input.focus();
    },
    options() { return [...this.$refs.options.querySelectorAll("button[data-name]")]; },
    highlight() {
      this.options().forEach((b, i) => b.classList.toggle("active", i === this.active));
    },
    clearOptions() {
      this.seq += 1; // svar sem er á leiðinni á ekki lengur við
      clearTimeout(this.timer);
      this.$refs.options.innerHTML = "";
      this.active = -1;
    },
    // Tillögur frá þjóninum. Raðnúmer tryggir að aðeins svar við nýjasta textanum birtist,
    // svo gamalt svar fylli ekki listann aftur eftir að gefandi var valinn.
    search() {
      this.active = -1;
      clearTimeout(this.timer);
      const seq = ++this.seq;
      this.timer = setTimeout(async () => {
        const q = this.$refs.input.value.trim();
        if (!q) { this.$refs.options.innerHTML = ""; return; }
        const url = `${this.$refs.input.dataset.searchUrl}?q=${encodeURIComponent(q)}`;
        try {
          const response = await fetch(url, { headers: { "HX-Request": "true" } });
          const html = await response.text();
          if (seq === this.seq && response.ok) this.$refs.options.innerHTML = html;
        } catch {
          /* netvilla: engar tillögur, hægt að skrifa nafnið samt */
        }
      }, 150);
    },

    addTag(name) {
      name = (name || "").trim();
      if (!name) return;
      const key = name.toLocaleLowerCase("is");
      if (!this.tags.some((t) => t.name.toLocaleLowerCase("is") === key)) this.tags.push({ name, share: "" });
      this.$refs.input.value = "";
      this.clearOptions();
    },
    removeTag(event) {
      this.tags.splice(Number(event.currentTarget.dataset.index), 1);
      if (!this.tags.length) this.forOther = false;
    },
    pick(event) {
      const button = event.target.closest("button[data-name]");
      if (button) this.addTag(button.dataset.name);
      this.$refs.input.focus();
    },
    commitTyped() { this.addTag(this.$refs.input.value); },
    onKey(event) {
      const options = this.options();
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!options.length) return;
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        this.active = (this.active + step + options.length) % options.length;
        this.highlight();
      } else if (event.key === "Enter" || event.key === ",") {
        event.preventDefault();
        if (this.active >= 0 && options[this.active]) this.addTag(options[this.active].dataset.name);
        else this.addTag(this.$refs.input.value);
      } else if (event.key === "Backspace" && !this.$refs.input.value && this.tags.length) {
        this.tags.pop();
        if (!this.tags.length) this.forOther = false;
      } else if (event.key === "Escape" && options.length) {
        event.preventDefault(); // loka tillögum, ekki glugganum
        this.clearOptions();
      }
    },

    toggleOther(event) { this.forOther = event.target.checked; },
    setShare(event) { this.tags[Number(event.target.dataset.index)].share = event.target.value; },
    setLink(event) { this.link = event.target.value.trim(); },
    storeChanged(event) {
      const locations = this.storeLocations[foldKey(event.target.value)];
      if (locations !== undefined) this.$refs.locations.value = locations;
    },
  }));
});

// CSRF-tóki fylgir öllum htmx-beiðnum (lesið úr <meta>, ekki inline-skriftu)
document.addEventListener("htmx:configRequest", (event) => {
  const token = document.querySelector('meta[name="csrf-token"]');
  if (token) event.detail.headers["X-CSRFToken"] = token.content;
});

// Gluggi opnast þegar htmx hefur sett efni í hann og unnið úr því (afterSettle, ekki afterSwap),
// svo ekki sé hægt að senda formið áður en htmx hefur tengt sig við það
document.addEventListener("htmx:afterSettle", (event) => {
  if (event.detail.target.id !== "modal-body") return;
  const modal = document.getElementById("modal");
  if (!modal.open) modal.showModal();
  const focus = modal.querySelector("[autofocus]");
  if (focus) focus.focus();
});

// Þjónninn sendir HX-Trigger: closeModal eftir vistun
document.body.addEventListener("closeModal", () => {
  const modal = document.getElementById("modal");
  if (modal && modal.open) modal.close();
});

// Villur sem ekki er hægt að sýna í glugga (t.d. 403 á læstu ári, netvilla)
function showError(text) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.querySelector("span").textContent = text;
  toast.querySelector("button")?.remove();
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 6000);
}
document.addEventListener("htmx:responseError", () => showError("Það tókst ekki að vista. Endurhladdu síðuna og reyndu aftur."));
document.addEventListener("htmx:sendError", () => showError("Engin tenging. Breytingin var ekki vistuð."));

// Annar í heimilinu gæti hafa breytt listanum: endurhlaða þegar flipinn verður sýnilegur aftur,
// nema eitthvað sé í vinnslu (reitur í fókus eða gluggi opinn)
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  const sections = document.getElementById("sections");
  const modal = document.getElementById("modal");
  const editing = document.activeElement && document.activeElement.matches("input, textarea, select");
  if (sections && !editing && !(modal && modal.open)) htmx.trigger(sections, "refresh");
});
