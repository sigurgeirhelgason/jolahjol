/*
 * Alpine-íhlutir. CSP-útgáfa Alpine leyfir ekki inline-segðir („open = !open“), svo öll
 * hegðun er skilgreind hér og sniðmátin vísa bara í nöfn eiginleika og aðferða.
 * Þessi skrá verður að hlaðast á undan Alpine (báðar með defer, í þessari röð).
 */
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
});

// CSRF-tóki fylgir öllum htmx-beiðnum (lesið úr <meta>, ekki inline-skriftu)
document.addEventListener("htmx:configRequest", (event) => {
  const token = document.querySelector('meta[name="csrf-token"]');
  if (token) event.detail.headers["X-CSRFToken"] = token.content;
});
