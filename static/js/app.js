/*
 * Alpine-íhlutir. CSP-útgáfa Alpine leyfir ekki inline-segðir („open = !open“), svo öll
 * hegðun er skilgreind hér og sniðmátin vísa bara í nöfn eiginleika og aðferða.
 * Þessi skrá verður að hlaðast á undan Alpine (báðar með defer, í þessari röð).
 */

// Elkó/Elko/ELKO → „elko“; sama regla og apps.core.text.fold_key
const foldKey = (s) => (s || "").trim().toLocaleLowerCase("is").normalize("NFD").replace(/[̀-ͯ]/g, "");

// dd/mm/áá → [ár, mánuður, dagur]; sama regla og BirthdayField (50 → 1950, 16 → 2016)
function parseBirthday(text) {
  const match = (text || "").trim().match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$/);
  if (!match) return null;
  let [, d, m, y] = match.map(Number);
  if (y < 100) y += 2000 + y <= new Date().getFullYear() ? 2000 : 1900;
  const date = new Date(y, m - 1, d);
  if (date.getMonth() !== m - 1 || date.getDate() !== d) return null;
  return [y, m, d];
}

// „Verður 8 ára 3. mars (eftir 119 daga)“. Samsvarar `birthdayInfo` í gamla appinu.
const MONTHS = ["jan.", "feb.", "mars", "apr.", "maí", "júní", "júlí", "ágúst", "sept.", "okt.", "nóv.", "des."];
function birthdayInfo(text) {
  const parsed = parseBirthday(text);
  if (!parsed) return "";
  const [y, m, d] = parsed;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let next = new Date(today.getFullYear(), m - 1, d);
  if (next < today) next = new Date(today.getFullYear() + 1, m - 1, d);
  const age = next.getFullYear() - y;
  const days = Math.round((next - today) / 86400000);
  if (age < 0) return "";
  if (days === 0) return `Á afmæli í dag – ${age} ára! 🎂`;
  return `Verður ${age} ára ${d}. ${MONTHS[m - 1]} (eftir ${days} ${days === 1 ? "dag" : "daga"})`;
}

function openConfirm(form) {
  const dialog = document.getElementById("confirm-dialog");
  if (!dialog) {
    if (window.confirm(form.dataset.message)) form.submit();
    return;
  }
  dialog.querySelector("#confirm-title").textContent = form.dataset.title || form.dataset.message;
  dialog.querySelector("#confirm-message").textContent = form.dataset.title ? form.dataset.message : "";
  const ok = dialog.querySelector("[data-confirm-ok]");
  ok.textContent = form.dataset.confirm || "Staðfesta";
  ok.onclick = () => {
    dialog.close();
    form.dataset.confirmed = "1";
    form.requestSubmit();
  };
  dialog.querySelector("[data-confirm-cancel]").onclick = () => dialog.close();
  dialog.onclick = (event) => { if (event.target === dialog) dialog.close(); };
  dialog.showModal();
  dialog.querySelector("[data-confirm-cancel]").focus(); // öruggari kosturinn fær fókus
}

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
  // Staðfesting á hættulegum aðgerðum: <form x-data="confirm" x-on:submit="ask" data-title="…"
  // data-message="…" data-confirm="Eyða">. Opnar #confirm-dialog; formið er sent ef staðfest er.
  Alpine.data("confirm", () => ({
    ask(event) {
      const form = this.$el;
      if (form.dataset.confirmed) {
        delete form.dataset.confirmed;
        return;
      }
      event.preventDefault();
      openConfirm(form);
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
      if (!this.$el.value.trim()) return;
      // Lína sem var að birtast er kannski ekki komin í gegnum htmx enn (settle); process er óskaðlegt
      htmx.process(this.$el);
      htmx.trigger(this.$el, "add");
      // htmx les gildið um leið og beiðnin fer af stað. Reiturinn er tæmdur strax svo að
      // blur (þegar línan er teiknuð upp á nýtt) sendi hugmyndina ekki aftur.
      this.$el.value = "";
    },
  }));

  // Gluggi (<dialog>) sem htmx fyllir; opnast þegar efni kemur og lokast við „closeModal“
  Alpine.data("modal", () => ({
    init() {
      // Smellur á bakgrunn lokar aðeins ef músinni var líka ýtt niður þar. Annars lokaðist
      // glugginn þegar texti var valinn í reit og músinni sleppt utan gluggans (vafrinn sendir
      // þá click á <dialog>, sameiginlegt foreldri beggja staða).
      // Bakgrunnur = utan við ramma gluggans (padding inni í glugganum hefur líka target === dialog).
      const outside = (event) => {
        const r = this.$el.getBoundingClientRect();
        return event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom;
      };
      let downOnBackdrop = false;
      this.$el.addEventListener("mousedown", (event) => {
        downOnBackdrop = event.target === this.$el && outside(event);
      });
      this.$el.addEventListener("click", (event) => {
        if (event.target.closest("[data-close]")) this.$el.close();
        else if (downOnBackdrop && event.target === this.$el && outside(event)) this.$el.close();
        downOnBackdrop = false;
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

  // Fæðingardagur í einstaklingsglugga: „Verður 8 ára 3. mars (eftir 119 daga)“
  Alpine.data("birthday", () => ({
    age: "",
    init() { this.update(); },
    update(event) {
      // Skástrik bætast við sjálfkrafa þegar skrifaðar eru tölur: 170516 → 17/05/16
      if (event && event.inputType && !event.inputType.startsWith("delete")) {
        const input = this.$refs.birthday;
        if (/^[\d/]*$/.test(input.value)) {
          const digits = input.value.replace(/\D/g, "").slice(0, 8);
          const parts = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)].filter(Boolean);
          input.value = parts.join("/") + (digits.length === 2 || digits.length === 4 ? "/" : "");
        }
      }
      this.age = birthdayInfo(this.$refs.birthday.value);
    },
  }));

  // Ný lína í flokki (eins og `addGift`): vistast þegar farið er úr línunni með nafni,
  // hverfur án nafns. Escape eða × hættir við.
  Alpine.data("newRow", () => ({
    sent: false,
    markSent() { this.sent = true; },
    leave(event) {
      if (this.sent || this.$el.contains(event.relatedTarget)) return;
      if (!this.$el.elements.name.value.trim()) { this.cancel(); return; }
      this.sent = true;
      htmx.trigger(this.$el, "submit");
    },
    cancel() {
      this.sent = true;
      this.$el.remove();
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
      this.tags = JSON.parse(this.$el.dataset.givers || "[]").map((name) => ({ name }));
      this.storeLocations = JSON.parse(this.$el.dataset.storeLocations || "{}");
      this.forOther = this.$refs.other.checked;
      this.link = this.$refs.link.value;
    },

    get hasGivers() { return this.tags.length > 0; },
    get showPaid() { return this.forOther && this.hasGivers; },
    // Placeholder hverfur þegar gefandi er kominn, því reiturinn er þá ekki „tómur“
    get placeholder() { return this.hasGivers ? "" : this.$refs.input.dataset.placeholder; },
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
      const value = this.$refs.input.value;
      if (value.includes(",")) {
        const parts = value.split(",");
        const rest = parts.pop();
        parts.forEach((name) => this.addTag(name));
        this.$refs.input.value = rest.trimStart();
        if (!this.$refs.input.value) return;
      }
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
      if (!this.tags.some((t) => t.name.toLocaleLowerCase("is") === key)) this.tags.push({ name });
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
        const typed = this.$refs.input.value.trim();
        if (event.key === "Enter" && !typed && this.active < 0) return; // tómur reitur: Enter vistar gluggann
        event.preventDefault();
        if (this.active >= 0 && options[this.active]) this.addTag(options[this.active].dataset.name);
        else this.addTag(typed);
      } else if (event.key === "Backspace" && !this.$refs.input.value && this.tags.length) {
        this.tags.pop();
        if (!this.tags.length) this.forOther = false;
      } else if (event.key === "Escape" && options.length) {
        event.preventDefault(); // loka tillögum, ekki glugganum
        this.clearOptions();
      }
    },

    toggleOther(event) { this.forOther = event.target.checked; },
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

// Gluggi opnast um leið og htmx setur efni í hann (afterSwap). htmx.process tengir formið strax,
// svo glugginn sé aldrei sýnilegur án þess að virka, og aldrei virkur án þess að vera sýnilegur
// (annars fer lyklaborðið á síðuna fyrir aftan á meðan beðið er eftir settle).
document.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id !== "modal-body") return;
  htmx.process(event.detail.target);
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
