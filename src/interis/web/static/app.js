// Interis review UI – plain JavaScript, no third-party code.
// Security: interview text is only ever inserted as text nodes (never innerHTML).
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function fmt(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function setStatus(text, isError = false) {
  const s = $("#status");
  s.textContent = text;
  s.classList.toggle("warn", isError);
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Interis": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) {
    $("#main").replaceChildren(el("p", { class: "empty" },
      "Nicht angemeldet. Bitte den Link öffnen, den `interis serve` im Terminal anzeigt."));
    throw new Error("not logged in");
  }
  if (!res.ok) {
    const msg = `Fehler ${res.status}: ${await res.text()}`;
    setStatus(msg, true);
    throw new Error(msg);
  }
  return res.json();
}

const MATCH_LABEL = { main: "Leitfadenfrage", probe: "geplante Nachfrage", followup: "spontane Nachfrage" };
const TYPE_LABEL = { anticipated: "vorweg beantwortet", later: "später nochmal",
                     unasked: "ohne Frage beantwortet" };
const STATUS_LABEL = { asked: "gestellt", answered_elsewhere: "nicht gestellt · an anderer Stelle beantwortet",
                       omitted: "weggelassen – schon beantwortet", missing: "nicht gestellt" };

function tagText(code, match) {
  if (match === "main" && code) return code;
  if (match === "probe" && code) return `${code} Nachfrage`;
  return "Nachfrage";
}

// ------------------------------------------------------------------ state
const state = {
  overview: null,
  hidden: new Set(JSON.parse(localStorage.getItem("interis.hidden") || "[]")),
  showSuggestions: localStorage.getItem("interis.sug") !== "0",
};
const guideQuestions = () => (state.overview?.guide?.questions) || [];
const guideText = (code) => guideQuestions().find((q) => q.code === code)?.text || "";

// ------------------------------------------------------------------ audio
const player = {
  audio: null, id: null, stopAt: null,
  attach(id, audio) { this.detach(); this.id = id; this.audio = audio; this._wire(); },
  detach() { if (this.audio) this.audio.pause(); this.audio = null; this.id = null; },
  _wire() {
    this.audio.addEventListener("timeupdate", () => {
      if (this.stopAt !== null && this.audio.currentTime >= this.stopAt) {
        this.audio.pause(); this.stopAt = null;
      }
    });
  },
  play(id, start, end) {
    const iv = state.overview?.interviews.find((i) => i.id === id);
    if (!iv?.has_audio) { setStatus(`Für ${id} ist keine Audiodatei hinterlegt.`, true); return; }
    if (this.id !== id) {
      this.detach();
      this.id = id;
      this.audio = new Audio(`/api/interviews/${encodeURIComponent(id)}/audio`);
      this._wire();
    }
    this.stopAt = end ?? null;
    const go = () => { this.audio.currentTime = Math.max(0, start - 0.15); this.audio.play(); };
    if (this.audio.readyState >= 1) go(); else this.audio.addEventListener("loadedmetadata", go, { once: true });
  },
};
const playBtn = (id, start, end, title = "abspielen") =>
  el("button", { class: "icon", title, onclick: (e) => { e.stopPropagation(); player.play(id, start, end); } }, "▶");

// ------------------------------------------------------------------ dialogs
function openDialog(...content) {
  const d = $("#dlg");
  d.replaceChildren(...content);
  d.showModal();
  return d;
}
const closeDialog = () => $("#dlg").close();

function guideSelect(selected, { allowNone = false, exclude = null } = {}) {
  const s = el("select");
  if (allowNone) s.append(el("option", { value: "" }, "— keine Leitfadenfrage (spontane Nachfrage) —"));
  for (const q of guideQuestions()) {
    if (q.code === exclude) continue;
    s.append(el("option", { value: q.code, selected: q.code === selected }, `${q.code} – ${q.text}`));
  }
  return s;
}

function linkDialog(interview, span, { defaultCode = null, excludeCode = null } = {}) {
  const select = guideSelect(defaultCode, { exclude: excludeCode });
  const omitted = el("input", { type: "checkbox" });
  const note = el("textarea", { rows: 2, placeholder: "Notiz (optional)" });
  openDialog(
    el("h2", {}, "Diese Stelle beantwortet (auch) …"),
    el("div", { class: "quote" }, span.text),
    select,
    el("div", { class: "row" }, el("label", {}, omitted,
      " Diese Leitfadenfrage habe ich deshalb weggelassen")),
    el("div", { class: "hint" }, "Nur ankreuzen, wenn die Frage in diesem Interview nicht gestellt wurde."),
    note,
    el("div", { class: "actions" },
      el("button", { onclick: closeDialog }, "Abbrechen"),
      el("button", { class: "primary", onclick: async () => {
        await api("POST", "/api/links", { interview, turn: span.turn, first: span.first, last: span.last,
          guide_code: select.value, omitted: omitted.checked, note: note.value });
        closeDialog(); await refresh("Verknüpfung gespeichert");
      } }, "Speichern")),
  );
}

function questionDialog(interview, q) {
  const select = guideSelect(q.guide_code, { allowNone: true });
  const kindMain = el("input", { type: "radio", name: "kind", checked: q.match !== "probe" });
  const kindProbe = el("input", { type: "radio", name: "kind", checked: q.match === "probe" });
  const body = { interview, turn: q.turn, first: q.first, last: q.last };
  openDialog(
    el("h2", {}, "Frage zuordnen"),
    el("div", { class: "quote" }, q.text),
    el("div", { class: "hint" }, "Welche Leitfadenfrage ist das (auch wenn anders formuliert)?"),
    select,
    el("div", { class: "row" },
      el("label", {}, kindMain, " Leitfadenfrage"),
      el("label", {}, kindProbe, " geplante Nachfrage dazu")),
    el("div", { class: "actions" },
      el("button", { title: "Markierung entfernen", onclick: async () => {
        await api("POST", "/api/questions", { ...body, guide_code: null, match: "followup", status: "rejected" });
        closeDialog(); await refresh("Als „keine Frage“ markiert");
      } }, "Ist keine Frage"),
      q.status === "confirmed" ? el("button", { title: "Automatische Erkennung wiederherstellen", onclick: async () => {
        await api("POST", "/api/questions/reset", { interview, turn: q.turn, first: q.first });
        closeDialog(); await refresh("Zurückgesetzt");
      } }, "Zurücksetzen") : null,
      el("button", { onclick: closeDialog }, "Abbrechen"),
      el("button", { class: "primary", onclick: async () => {
        const code = select.value || null;
        await api("POST", "/api/questions", { ...body, guide_code: code,
          match: code ? (kindProbe.checked ? "probe" : "main") : "followup", status: "confirmed" });
        closeDialog(); await refresh("Frage gespeichert");
      } }, "Speichern")),
  );
}

// ------------------------------------------------------------------ routing
async function refresh(msg) {
  const scroller = $(".gridwrap") || document.scrollingElement;
  const pos = [scroller.scrollLeft, scroller.scrollTop];
  await route(true);
  const again = $(".gridwrap") || document.scrollingElement;
  again.scrollLeft = pos[0]; again.scrollTop = pos[1];
  if (msg) setStatus(msg);
}

async function route(keepScroll = false) {
  hideSelbar();
  state.overview = await api("GET", "/api/overview");
  renderNav();
  const h = location.hash;
  if (h.startsWith("#/i/")) {
    const [id, query] = h.slice(4).split("?");
    const turn = new URLSearchParams(query || "").get("t");
    await renderInterview(decodeURIComponent(id), turn === null ? null : Number(turn), keepScroll);
  } else {
    player.detach();
    await renderCompare();
  }
}

function renderNav() {
  const nav = $("#nav");
  const current = location.hash.startsWith("#/i/") ? decodeURIComponent(location.hash.slice(4).split("?")[0]) : null;
  nav.replaceChildren(
    el("a", { href: "#/", class: current ? "" : "active" }, "Vergleich"),
    ...state.overview.interviews.map((iv) =>
      el("a", { href: `#/i/${encodeURIComponent(iv.id)}`, class: iv.id === current ? "active" : "" }, iv.id)),
  );
}

// ------------------------------------------------------------------ comparison view
async function renderCompare() {
  const data = await api("GET", "/api/compare");
  const main = $("#main");
  if (!data.guide) {
    main.replaceChildren(el("p", { class: "empty" },
      "Kein Leitfaden gefunden. Lege leitfaden.md in den Datenordner oder starte mit --guide."));
    return;
  }
  if (!data.interviews.length) {
    main.replaceChildren(el("p", { class: "empty" }, "Noch keine Interviews. Erst mit `interis transcribe` transkribieren."));
    return;
  }
  const ids = data.interviews.filter((id) => !state.hidden.has(id));
  const toolbar = el("div", { class: "toolbar" },
    el("strong", {}, "Interviews:"),
    ...data.interviews.map((id) => el("label", {},
      el("input", { type: "checkbox", checked: !state.hidden.has(id), onchange: (e) => {
        if (e.target.checked) state.hidden.delete(id); else state.hidden.add(id);
        localStorage.setItem("interis.hidden", JSON.stringify([...state.hidden])); refresh();
      } }), id)),
    el("label", {}, el("input", { type: "checkbox", checked: state.showSuggestions, onchange: (e) => {
      state.showSuggestions = e.target.checked; localStorage.setItem("interis.sug", e.target.checked ? "1" : "0"); refresh();
    } }), "Vorschläge anzeigen"),
  );

  const grid = el("div", { class: "grid" });
  grid.style.gridTemplateColumns = `minmax(220px, 280px) repeat(${ids.length}, minmax(320px, 420px))`;
  grid.append(el("div", { class: "hcell gcell" }, "Leitfaden"));
  for (const id of ids) {
    const iv = state.overview.interviews.find((i) => i.id === id);
    grid.append(el("div", { class: "hcell" },
      el("a", { href: `#/i/${encodeURIComponent(id)}` }, id),
      el("div", { class: "meta" }, fmt(iv.duration_s), iv.has_audio ? "" : " · kein Audio",
        iv.has_roles ? "" : " · Rollen unbekannt"),
      iv.guide_mismatch ? el("div", { class: "meta warn" }, "mit anderem Leitfaden analysiert – `interis analyze` ausführen") : null));
  }

  let section = null;
  for (const gq of data.guide.questions) {
    if (gq.section && gq.section !== section) {
      section = gq.section;
      grid.append(el("div", { class: "section" }, section));
    }
    grid.append(el("div", { class: "gcell" },
      el("span", { class: "code" }, gq.code), gq.text,
      gq.variants.length ? el("div", { class: "variants" }, "auch: ", gq.variants.join(" · ")) : null));
    for (const id of ids) grid.append(compareCell(id, gq, data.cells[id][gq.code]));
  }

  grid.append(el("div", { class: "section" }, "Fragen ohne Leitfaden-Zuordnung"));
  grid.append(el("div", { class: "gcell" }, el("span", { class: "variants" },
    "Spontane Nachfragen. Mit ✎ einer Leitfadenfrage zuordnen, falls es eine war.")));
  for (const id of ids) {
    const list = data.unassigned[id] || [];
    grid.append(el("div", { class: "cell unassigned" },
      list.length ? list.map((q) => el("div", { class: "dturn" },
        playBtn(id, q.start, q.end), el("span", { class: "time" }, fmt(q.start), " "),
        q.text, " ", el("button", { class: "icon", title: "zuordnen", onclick: () => questionDialog(id, q) }, "✎")))
        : el("span", { class: "time" }, "–")));
  }

  main.replaceChildren(toolbar, el("div", { class: "gridwrap" }, grid));
}

function compareCell(id, gq, c) {
  const cell = el("div", { class: `cell st-${c.status}` });
  const asked = c.exchanges.map((x) => fmt(x.start)).join(", ");
  cell.append(el("div", { class: "status" }, STATUS_LABEL[c.status], asked ? ` · ${asked}` : ""));

  for (const ex of c.exchanges) {
    const box = el("div", { class: "exchange" });
    for (const t of ex.dialogue) box.append(dialogueTurn(id, gq.code, t));
    cell.append(box);
  }

  if (c.links.length) {
    cell.append(el("div", { class: "sub" }, c.exchanges.length ? "Auch beantwortet an anderer Stelle:" : "Beantwortet an anderer Stelle:"));
    for (const lk of c.links) cell.append(linkItem(id, lk));
  }
  if (state.showSuggestions && c.suggestions.length) {
    cell.append(el("div", { class: "sub" }, "Vorschläge (bitte prüfen):"));
    for (const s of c.suggestions) cell.append(suggestionItem(id, gq.code, s));
  }
  if (!c.exchanges.length && !c.links.length) {
    cell.append(el("div", { class: "hint time" }, "Tipp: im Transkript eine Stelle markieren → „Antwort auf …“."));
  }
  return cell;
}

function dialogueTurn(id, code, t) {
  const short = t.role === "interviewer" ? "I" : t.role === "interviewee" ? "B" : t.speaker;
  const node = el("div", { class: `dturn role-${t.role}` },
    playBtn(id, t.start, t.end), el("span", { class: "who", title: t.speaker }, `${short}:`));
  for (const p of t.pieces) {
    if (p.question) {
      const cls = p.match === "followup" ? "followup" : "";
      node.append(el("span", { class: `tag ${cls}`, title: "Zuordnung ändern",
        onclick: () => questionDialog(id, { ...p, guide_code: p.code }) }, tagText(p.code, p.match)),
      el("span", { class: `qspan ${cls}` }, p.text), " ");
    } else {
      node.append(p.text, " ");
    }
  }
  if (t.role !== "interviewer") {
    node.append(el("button", { class: "icon", title: "Diese Antwort beantwortet auch eine andere Frage …",
      onclick: () => linkDialog(id, { turn: t.turn, first: 0, last: t.n_words - 1,
        text: t.pieces.map((p) => p.text).join(" ") }, { excludeCode: code }) }, "↗"));
  }
  node.append(el("a", { class: "icon time", href: `#/i/${encodeURIComponent(id)}?t=${t.turn}`, title: "im Transkript öffnen" }, " ⤴"));
  return node;
}

function linkItem(id, lk) {
  return el("div", { class: "item link" },
    el("div", { class: "head" },
      playBtn(id, lk.start, lk.end),
      el("span", { class: "time" }, fmt(lk.start)),
      el("span", { class: "kind" }, TYPE_LABEL[lk.type]),
      lk.from_code ? el("span", { class: "time" }, `(aus der Antwort auf ${lk.from_code})`) : null,
      lk.type === "unasked" ? el("label", {}, el("input", { type: "checkbox", checked: lk.omitted, onchange: async (e) => {
        await api("PATCH", `/api/links/${lk.id}`, { omitted: e.target.checked }); await refresh("Gespeichert");
      } }), "deshalb weggelassen") : null,
      el("button", { class: "icon", title: "Verknüpfung löschen", onclick: async () => {
        await api("DELETE", `/api/links/${lk.id}`); await refresh("Verknüpfung gelöscht");
      } }, "✕"),
      el("a", { class: "icon time", href: `#/i/${encodeURIComponent(id)}?t=${lk.turn}`, title: "im Transkript öffnen" }, "⤴")),
    el("div", { class: "txt" }, lk.text),
    lk.note ? el("div", { class: "time" }, "Notiz: ", lk.note) : null);
}

function suggestionItem(id, code, s) {
  const decide = (status) => async () => {
    await api("POST", "/api/links", { interview: id, turn: s.turn, first: s.first, last: s.last,
      guide_code: code, status, source: "suggestion", omitted: false });
    await refresh(status === "confirmed" ? "Vorschlag übernommen" : "Vorschlag verworfen");
  };
  return el("div", { class: "item sug" },
    el("div", { class: "head" },
      playBtn(id, s.start, s.end),
      el("span", { class: "time" }, fmt(s.start)),
      el("span", { class: "kind" }, `evtl. ${TYPE_LABEL[s.type]}`),
      s.from_code ? el("span", { class: "time" }, `(aus der Antwort auf ${s.from_code})`) : null,
      el("button", { title: "übernehmen", onclick: decide("confirmed") }, "✓"),
      el("button", { title: "verwerfen", onclick: decide("rejected") }, "✕"),
      el("a", { class: "icon time", href: `#/i/${encodeURIComponent(id)}?t=${s.turn}`, title: "im Transkript öffnen" }, "⤴")),
    el("div", { class: "txt" }, s.text));
}

// ------------------------------------------------------------------ transcript view
async function renderInterview(id, focusTurn, keepScroll) {
  const d = await api("GET", `/api/interviews/${encodeURIComponent(id)}`);
  const iv = state.overview.interviews.find((i) => i.id === id);
  const names = Object.fromEntries(d.speakers.map((s) => [s.label, s]));

  // word-level lookups for questions and confirmed links
  const qAt = new Map(); // "ti:wi" -> question
  for (const q of d.questions) for (let w = q.first; w <= q.last; w++) qAt.set(`${q.turn}:${w}`, q);
  const linkAt = new Map(); // "ti:wi" -> [links]
  for (const lk of d.links.filter((l) => l.status === "confirmed")) {
    for (let w = lk.first; w <= lk.last; w++) {
      const k = `${lk.turn}:${w}`;
      linkAt.set(k, [...(linkAt.get(k) || []), lk]);
    }
  }

  let audio = null;
  const parts = [];
  if (iv?.has_audio) {
    audio = el("audio", { controls: true, preload: "metadata", src: `/api/interviews/${encodeURIComponent(id)}/audio` });
    parts.push(el("div", { class: "player" }, audio));
  }

  const tr = el("div", { class: "transcript" });
  d.turns.forEach((turn, ti) => {
    const sp = names[turn.speaker] || {};
    const row = el("div", { class: `tturn role-${sp.role || "unknown"}`, id: `t-${ti}`, dataset: { ti, start: turn.start } },
      el("span", { class: "time" }, fmt(turn.start), " "),
      el("span", { class: "who" }, `${sp.display_name || turn.speaker || "?"}:`));
    turn.words.forEach((w, wi) => {
      const q = qAt.get(`${ti}:${wi}`);
      const lks = linkAt.get(`${ti}:${wi}`);
      if (q && wi === q.first) {
        row.append(el("span", { class: `tag ${q.match === "followup" || !q.guide_code ? "followup" : ""}`,
          title: `${MATCH_LABEL[q.match] || "Frage"} – klicken zum Zuordnen`, onclick: () => questionDialog(id, q) },
          q.guide_code ? tagText(q.guide_code, q.match) : q.match === "followup" ? "Nachfrage" : "Frage?"));
      }
      if (lks) for (const lk of lks) if (wi === lk.first) {
        row.append(el("span", { class: "tag link", title: `beantwortet ${lk.guide_code}: ${guideText(lk.guide_code)} – klicken zum Löschen`,
          onclick: async () => {
            if (confirm(`Verknüpfung mit ${lk.guide_code} löschen?`)) { await api("DELETE", `/api/links/${lk.id}`); await refresh("Gelöscht"); }
          } }, `↗${lk.guide_code}`));
      }
      const cls = ["w", q ? "q" : "", lks ? "lk" : "", w.p < 0.5 ? "low" : ""].join(" ").trim();
      row.append(el("span", { class: cls, dataset: { ti, wi, s: w.s }, title: w.p < 0.5 ? `unsicher (${Math.round(w.p * 100)} %)` : null }, w.t));
    });
    tr.append(row);
  });

  // sidebar: guide coverage for this interview
  const side = el("div", { class: "side" }, el("h3", {}, "Leitfaden in diesem Interview"));
  const cov = el("div", { class: "cov" });
  for (const gq of guideQuestions()) {
    const c = d.cells[gq.code];
    if (!c) continue;
    const first = c.exchanges[0];
    const statusCls = c.status === "asked" ? "ok" : c.status === "missing" ? "" : "el";
    const target = first ? first.question.turn : c.links[0]?.turn;
    cov.append(el("span", { class: "c", title: gq.text }, gq.code),
      el("span", { class: `s ${statusCls}` },
        target !== undefined ? el("a", { href: `#/i/${encodeURIComponent(id)}?t=${target}` }, STATUS_LABEL[c.status], first ? ` ${fmt(first.start)}` : "")
          : STATUS_LABEL[c.status]));
  }
  side.append(cov,
    el("h3", {}, "Bedienung"),
    el("div", { class: "legend" },
      el("p", {}, "Text mit der Maus markieren → „Als Frage markieren“ oder „Antwort auf …“."),
      el("p", {}, "Auf ein Wort klicken → Audio springt dorthin."),
      el("p", {}, el("span", { class: "tag" }, "F1"), "Frage  ", el("span", { class: "tag link" }, "↗F3"), "beantwortet auch F3  ",
        el("span", { class: "w low" }, "unsicher"))));

  const header = el("div", { class: "toolbar" }, el("a", { href: "#/" }, "← Vergleich"), el("strong", {}, `Interview ${id}`),
    iv?.has_audio ? null : el("span", { class: "warn" }, "Keine Audiodatei hinterlegt (interis set-audio)."));
  const scrollY = window.scrollY;
  $("#main").replaceChildren(header, ...parts, el("div", { class: "iview" }, tr, side));

  if (audio) {
    player.attach(id, audio);
    const turnsEls = [...tr.children];
    let current = null;
    audio.addEventListener("timeupdate", () => {
      const t = audio.currentTime;
      let found = null;
      for (const r of turnsEls) { if (Number(r.dataset.start) <= t) found = r; else break; }
      if (found !== current) { current?.classList.remove("playing"); found?.classList.add("playing"); current = found; }
    });
  }
  tr.addEventListener("click", (e) => {
    const w = e.target.closest(".w");
    if (!w || !audio || !window.getSelection().isCollapsed) return;
    audio.currentTime = Number(w.dataset.s); audio.play();
  });
  tr.addEventListener("mouseup", () => setTimeout(() => onSelect(id, d), 0));

  if (keepScroll) window.scrollTo(0, scrollY);
  else if (focusTurn !== null) {
    const target = $(`#t-${focusTurn}`);
    if (target) { target.scrollIntoView({ block: "center" }); target.classList.add("flash"); }
  } else window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ text selection → actions
function hideSelbar() { $("#selbar").hidden = true; }
document.addEventListener("mousedown", (e) => { if (!e.target.closest("#selbar")) hideSelbar(); });

function onSelect(id, d) {
  const sel = window.getSelection();
  if (sel.isCollapsed || !sel.rangeCount) return;
  const wordOf = (node) => (node?.nodeType === 3 ? node.parentElement : node)?.closest?.(".w");
  let a = wordOf(sel.anchorNode), b = wordOf(sel.focusNode);
  if (!a || !b) return;
  if (a.dataset.ti !== b.dataset.ti) { setStatus("Bitte nur innerhalb eines Sprecherbeitrags markieren.", true); return; }
  const turn = Number(a.dataset.ti);
  let first = Number(a.dataset.wi), last = Number(b.dataset.wi);
  if (first > last) [first, last] = [last, first];
  const words = d.turns[turn].words.slice(first, last + 1);
  const span = { turn, first, last, text: words.map((w) => w.t).join("").trim() };

  const rect = sel.getRangeAt(0).getBoundingClientRect();
  const bar = $("#selbar");
  bar.replaceChildren(
    el("button", { onclick: () => { hideSelbar(); questionDialog(id, { ...span, guide_code: null, match: "main", status: "new" }); } }, "Als Frage markieren"),
    el("button", { onclick: () => { hideSelbar(); linkDialog(id, span); } }, "Antwort auf Frage …"),
  );
  bar.style.left = `${Math.max(8, rect.left)}px`;
  bar.style.top = `${Math.max(56, rect.top - 40)}px`;
  bar.hidden = false;
}

// ------------------------------------------------------------------ start
async function start() {
  const m = location.hash.match(/login=([A-Za-z0-9_-]+)/);
  if (m) {
    await api("POST", "/api/login", { token: m[1] });
    history.replaceState(null, "", location.pathname + "#/"); // remove token from the address bar
  }
  window.addEventListener("hashchange", () => route());
  await route();
}
start().catch((e) => console.error(e));
