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
  overview: null,   // /api/projects/{pid} of the open project
  pid: null,
  hidden: new Set(JSON.parse(localStorage.getItem("interis.hidden") || "[]")),
  showSuggestions: localStorage.getItem("interis.sug") !== "0",
};
const guideQuestions = () => (state.overview?.guide?.questions) || [];
const pHref = (rest = "") => `#/p/${state.pid}${rest}`;
const iHref = (id, turn) => pHref(`/i/${encodeURIComponent(id)}${turn === undefined || turn === null ? "" : `?t=${turn}`}`);
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
  stopPolling();
  const h = location.hash;
  const m = h.match(/^#\/p\/(\d+)(.*)$/);
  if (!m) {
    player.detach();
    state.pid = null; state.overview = null;
    renderNav();
    await renderProjects();
    return;
  }
  state.pid = Number(m[1]);
  state.overview = await api("GET", `/api/projects/${state.pid}`);
  const rest = m[2];
  renderNav(rest);
  if (rest.startsWith("/i/")) {
    const [id, query] = rest.slice(3).split("?");
    const turn = new URLSearchParams(query || "").get("t");
    await renderInterview(decodeURIComponent(id), turn === null ? null : Number(turn), keepScroll);
  } else if (rest.startsWith("/setup")) {
    player.detach();
    renderSetup();
  } else {
    player.detach();
    await renderCompare();
  }
}

function renderNav(rest = "") {
  const nav = $("#nav");
  if (state.pid === null) { nav.replaceChildren(); return; }
  const current = rest.startsWith("/i/") ? decodeURIComponent(rest.slice(3).split("?")[0]) : null;
  const done = state.overview.interviews.filter((iv) => iv.transcribed);
  nav.replaceChildren(
    el("span", { class: "pname" }, state.overview.project.name),
    el("a", { href: pHref(), class: !current && !rest.startsWith("/setup") ? "active" : "" }, "Vergleich"),
    el("a", { href: pHref("/setup"), class: rest.startsWith("/setup") ? "active" : "" }, "Leitfaden & Interviews"),
    ...done.map((iv) => el("a", { href: iHref(iv.id), class: iv.id === current ? "active" : "" }, iv.id)),
  );
}

// ------------------------------------------------------------------ polling (job progress)
let pollTimer = null;
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
function startPolling(fn, ms = 2000) { stopPolling(); pollTimer = setInterval(() => fn().catch(stopPolling), ms); }

// ------------------------------------------------------------------ project list
async function renderProjects() {
  const projects = await api("GET", "/api/projects");
  const name = el("input", { type: "text", placeholder: "z. B. Masterarbeit – Interviews Pflege", maxlength: 200, size: 40 });
  const create = async () => {
    if (!name.value.trim()) { name.focus(); return; }
    const r = await api("POST", "/api/projects", { name: name.value.trim() });
    location.hash = `#/p/${r.id}/setup`;
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") create(); });
  const list = el("div", { class: "cards" }, projects.map((p) => el("a", { class: "card", href: p.transcribed && p.questions ? `#/p/${p.id}` : `#/p/${p.id}/setup` },
    el("h3", {}, p.name),
    el("div", { class: "time" },
      `${p.questions} Leitfadenfragen · ${p.transcribed} von ${p.interviews} Interviews transkribiert`),
    p.active_jobs ? el("div", { class: "running" }, `${p.active_jobs} Auftrag/Aufträge in Arbeit …`) : null)));
  $("#main").replaceChildren(el("div", { class: "page" },
    el("h2", {}, "Projekte"),
    el("p", { class: "time" }, "Ein Projekt = ein Interviewleitfaden + die Interviews dazu. Alles bleibt auf diesem Rechner."),
    projects.length ? list : el("p", { class: "empty" }, "Noch keine Projekte."),
    el("div", { class: "box" }, el("h3", {}, "Neues Projekt"),
      el("div", { class: "row" }, name, el("button", { class: "primary", onclick: create }, "Anlegen")))));
  if (projects.some((p) => p.active_jobs)) startPolling(async () => { if (!state.pid) await renderProjects(); }, 5000);
}

// ------------------------------------------------------------------ setup: guide + interviews
const GUIDE_TEMPLATE = `# Leitfaden

## Einstieg
- F1: Erzählen Sie mir bitte, wie Ihr Arbeitsalltag aussieht.
  ~ Wie sieht ein typischer Tag bei Ihnen aus?
  > Seit wann machen Sie das?

## Hauptteil
- F2: …
`;

const STAGES = ["hash", "decode", "transcribe", "align", "diarize", "analyze"];
const STAGE_LABEL = { start: "Start, Modelle laden", hash: "Datei prüfen", decode: "Audio lesen",
  transcribe: "Spracherkennung", align: "Wörter ausrichten", diarize: "Sprechertrennung", analyze: "Fragen erkennen" };

function renderSetup() {
  const ov = state.overview;
  const main = $("#main");

  // --- project settings
  const pname = el("input", { type: "text", value: ov.project.name, maxlength: 200, size: 40 });
  const hot = el("input", { type: "text", value: ov.project.hotwords, maxlength: 2000, size: 60,
    placeholder: "z. B. Müller-Lüdenscheidt, SAP S/4HANA, Pflegedokumentation" });
  const projectBox = el("div", { class: "box" }, el("h3", {}, "Projekt"),
    el("label", { class: "field" }, "Name", pname),
    el("label", { class: "field" }, "Glossar (Namen, Fachbegriffe – hilft bei der Schreibweise, gilt für neue Transkriptionen)", hot),
    el("div", { class: "actions" }, el("button", { onclick: async () => {
      await api("PATCH", `/api/projects/${state.pid}`, { name: pname.value.trim() || ov.project.name, hotwords: hot.value });
      await refresh("Projekt gespeichert");
    } }, "Speichern")));

  // --- guide editor
  const ta = el("textarea", { class: "guide-edit", rows: 22, spellcheck: "true" });
  ta.value = ov.guide_text || GUIDE_TEMPLATE;
  const preview = el("div", { class: "guide-preview" });
  const gstatus = el("span", { class: "time" });
  let timer = null, dirty = !ov.guide_text;
  const updatePreview = async () => {
    const r = await api("POST", "/api/guide/parse", { text: ta.value });
    if (r.error) { preview.replaceChildren(el("p", { class: "warn" }, r.error)); return; }
    let section = null;
    const items = [];
    for (const q of r.guide.questions) {
      if (q.section && q.section !== section) { section = q.section; items.push(el("div", { class: "psec" }, section)); }
      items.push(el("div", { class: "pq" }, el("span", { class: "code" }, q.code), q.text,
        q.variants.length ? el("div", { class: "variants" }, "auch: ", q.variants.join(" · ")) : null,
        q.probes.length ? el("div", { class: "variants" }, "Nachfragen: ", q.probes.join(" · ")) : null));
    }
    preview.replaceChildren(el("div", { class: "time" }, `${r.guide.questions.length} Fragen erkannt`), ...items);
  };
  ta.addEventListener("input", () => {
    dirty = true; gstatus.textContent = "nicht gespeichert";
    clearTimeout(timer); timer = setTimeout(updatePreview, 350);
  });
  if (dirty) gstatus.textContent = "Vorlage – bitte anpassen und speichern";

  const fileIn = el("input", { type: "file", accept: ".md,.txt,.docx", hidden: true, onchange: async () => {
    const f = fileIn.files[0]; fileIn.value = "";
    if (!f) return;
    if (f.name.toLowerCase().endsWith(".docx")) {
      const res = await fetch("/api/guide/import-docx", { method: "POST", credentials: "same-origin",
        headers: { "X-Interis": "1", "Content-Type": "application/octet-stream" }, body: f });
      if (!res.ok) { setStatus(`Word-Datei: ${(await res.json()).detail}`, true); return; }
      ta.value = (await res.json()).text;
      setStatus("Word-Datei übernommen – bitte prüfen: nur Zeilen mit „- “ gelten als Fragen.");
    } else {
      ta.value = await f.text();
    }
    ta.dispatchEvent(new Event("input"));
  } });
  const linesToQuestions = () => {
    ta.value = ta.value.split("\n").map((line) => {
      const t = line.trim();
      if (!t || /^(#|[-*~>]|\d+[.)]\s)/.test(t)) return line;
      return `- ${t}`;
    }).join("\n");
    ta.dispatchEvent(new Event("input"));
  };
  const saveGuide = async () => {
    const r = await api("PUT", `/api/projects/${state.pid}/guide`, { text: ta.value });
    dirty = false; gstatus.textContent = "gespeichert";
    await refresh(`Leitfaden gespeichert: ${r.questions} Fragen` +
      (r.reanalyze ? ` – ${r.reanalyze} Interview(s) werden neu analysiert` : ""));
  };
  const guideBox = el("div", { class: "box" },
    el("h3", {}, "Leitfaden (die Fragen, die du stellen wolltest)"),
    el("details", { class: "time" }, el("summary", {}, "Format"),
      el("pre", {}, "## Abschnitt\n- F1: Frage …            ← jede Frage beginnt mit „- “, Kürzel optional\n" +
        "  ~ andere Formulierung  ← wenn du sie manchmal anders stellst\n  > geplante Nachfrage")),
    el("div", { class: "row" },
      el("button", { onclick: () => fileIn.click() }, "Datei laden (.docx, .md, .txt)"), fileIn,
      el("button", { title: "Macht aus jeder einfachen Textzeile eine Frage", onclick: linesToQuestions }, "Jede Zeile als Frage"),
      el("button", { class: "primary", onclick: saveGuide }, "Leitfaden speichern"), gstatus),
    el("div", { class: "guide-split" }, ta, preview));
  updatePreview();

  // --- upload
  const audioIn = el("input", { type: "file", accept: "audio/*,video/*,.m4a,.mp3,.wav,.aac,.flac,.ogg,.opus,.wma,.mp4,.mov,.mkv" });
  const idIn = el("input", { type: "text", value: ov.next_id, maxlength: 40, size: 8, pattern: "[A-Za-z0-9_\\-]+" });
  const model = el("select", {},
    el("option", { value: "whisper-large-v3" }, "Genau (large-v3, empfohlen)"),
    el("option", { value: "whisper-large-v3-turbo" }, "Schneller Entwurf (large-v3-turbo)"));
  const bar = el("progress", { max: 100, value: 0, hidden: true });
  const upBtn = el("button", { class: "primary" }, "Hochladen & transkribieren");
  upBtn.addEventListener("click", () => {
    const f = audioIn.files[0];
    if (!f) { setStatus("Bitte zuerst eine Aufnahme auswählen.", true); return; }
    const ext = (f.name.match(/\.([A-Za-z0-9]+)$/) || [])[1] || "";
    const q = new URLSearchParams({ interview: idIn.value.trim(), ext, model: model.value });
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${state.pid}/interviews?${q}`);
    xhr.setRequestHeader("X-Interis", "1");
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.value = (100 * e.loaded) / e.total; };
    xhr.onload = async () => {
      bar.hidden = true; upBtn.disabled = false;
      if (xhr.status !== 200) {
        let msg = xhr.responseText;
        try { msg = JSON.parse(msg).detail; } catch { /* plain text */ }
        setStatus(`Upload fehlgeschlagen: ${msg}`, true); return;
      }
      await refresh(`${idIn.value} hochgeladen – Transkription eingereiht`);
    };
    xhr.onerror = () => { bar.hidden = true; upBtn.disabled = false; setStatus("Upload fehlgeschlagen", true); };
    bar.hidden = false; bar.value = 0; upBtn.disabled = true;
    setStatus("Lade hoch …");
    xhr.send(f);
  });
  const uploadBox = el("div", { class: "box" },
    el("h3", {}, "Interview hinzufügen"),
    el("div", { class: "row" },
      el("label", { class: "field" }, "Aufnahme", audioIn),
      el("label", { class: "field" }, "Kürzel (Pseudonym)", idIn),
      el("label", { class: "field" }, "Genauigkeit", model)),
    el("div", { class: "row" }, upBtn, bar),
    el("p", { class: "time" },
      "Die Aufnahme wird als „", el("code", {}, `audio\\${ov.next_id}.<endung>`),
      "“ in deinen Datenordner kopiert; der Dateiname wird nicht übernommen. " +
      "Dauer: etwa 35–40 s pro Audiominute auf diesem PC (Laptop ca. doppelt so lange). " +
      "Die Website darf offen bleiben oder geschlossen werden, nur „interis serve“ muss laufen."));

  // --- interview list with job status
  const listBox = el("div", { class: "box" });
  const renderList = () => {
    const ivs = state.overview.interviews;
    const mismatch = ivs.some((iv) => iv.guide_mismatch);
    listBox.replaceChildren(...[
      el("h3", {}, "Interviews in diesem Projekt"),
      mismatch ? el("p", { class: "warn" }, "Einige Interviews wurden mit einem älteren Leitfaden analysiert. ",
        el("button", { onclick: async () => {
          const r = await api("POST", `/api/projects/${state.pid}/reanalyze`);
          await refresh(`${r.reanalyze} Interview(s) werden neu analysiert`);
        } }, "Neu analysieren")) : null,
      ivs.length ? el("table", { class: "jobs" },
        el("tr", {}, el("th", {}, "Kürzel"), el("th", {}, "Dauer"), el("th", {}, "Status"), el("th", {}, "")),
        ivs.map(interviewRow)) : el("p", { class: "time" }, "Noch keine Interviews."),
    ].filter(Boolean));
  };
  renderList();

  main.replaceChildren(el("div", { class: "page" }, projectBox, guideBox, uploadBox, listBox));

  const active = () => state.overview.interviews.some((iv) => ["queued", "running"].includes(iv.job?.status));
  if (active()) {
    startPolling(async () => {
      const before = state.overview.interviews.filter((iv) => iv.transcribed).length;
      state.overview = await api("GET", `/api/projects/${state.pid}`);
      renderList();
      if (state.overview.interviews.filter((iv) => iv.transcribed).length !== before) renderNav("/setup");
      if (!active()) stopPolling();
    });
  }
}

function interviewRow(iv) {
  const j = iv.job;
  let status, actions = [];
  const busy = j && ["queued", "running"].includes(j.status);
  if (busy && j.status === "queued") {
    status = el("span", {}, j.kind === "analyze" ? "Analyse wartet" : "wartet", j.queue_pos ? ` (Position ${j.queue_pos + 1})` : "");
  } else if (busy) {
    const key = (j.stage || "start").split(":")[0];
    const step = STAGES.indexOf(key);
    status = j.kind === "analyze" ? el("span", { class: "running" }, "Fragen werden neu erkannt …")
      : el("span", { class: "running" },
        step >= 0 ? `Schritt ${step + 1}/${STAGES.length}: ` : "", STAGE_LABEL[key] || key,
        j.progress > 0 && j.progress < 1 ? ` ${Math.round(j.progress * 100)} %` : " …",
        el("progress", { max: 1, value: step >= 0 ? (step + j.progress) / STAGES.length : 0 }),
        j.started_at ? el("span", { class: "time" }, ` seit ${new Date(j.started_at).toLocaleTimeString()}`) : null);
  } else if (j && j.status === "failed") {
    status = el("span", { class: "warn", title: j.message }, "Fehler: ", j.message.split("\n").pop());
  } else if (j && j.status === "cancelled") {
    status = el("span", { class: "time" }, "abgebrochen");
  } else if (iv.transcribed) {
    status = el("span", { class: "ok" }, "fertig", iv.guide_mismatch ? el("span", { class: "warn" }, " · älterer Leitfaden") : null,
      iv.has_roles ? null : el("span", { class: "time" }, " · Rollen unklar"));
  } else {
    status = el("span", { class: "time" }, "keine Transkription");
  }
  if (busy) actions.push(el("button", { onclick: async () => {
    if (!confirm(`${iv.id}: Auftrag abbrechen? Bereits fertige Schritte bleiben zwischengespeichert.`)) return;
    await api("POST", `/api/jobs/${j.id}/cancel`); await refresh("Abgebrochen");
  } }, "Abbrechen"));
  if (j && ["failed", "cancelled"].includes(j.status)) actions.push(el("button", { onclick: async () => {
    await api("POST", `/api/jobs/${j.id}/retry`); await refresh("Neu eingereiht");
  } }, "Erneut starten"));
  if (iv.transcribed) actions.push(el("a", { href: iHref(iv.id) }, "Transkript öffnen"));
  if (!busy) actions.push(el("button", { class: "icon", title: "Interview aus Interis entfernen", onclick: async () => {
    if (!confirm(`${iv.id} entfernen?

Gelöscht werden: Transkript, Zwischenergebnisse, deine Markierungen ` +
      "und die hochgeladene Kopie der Aufnahme. Deine Originaldatei bleibt, wo sie ist.")) return;
    await api("DELETE", `/api/interviews/${encodeURIComponent(iv.id)}`); await refresh(`${iv.id} entfernt`);
  } }, "🗑"));
  return el("tr", {}, el("td", {}, el("strong", {}, iv.id)), el("td", {}, iv.duration_s ? fmt(iv.duration_s) : "–"),
    el("td", {}, status), el("td", { class: "acts" }, actions));
}

// ------------------------------------------------------------------ comparison view
async function renderCompare() {
  const data = await api("GET", `/api/projects/${state.pid}/compare`);
  const main = $("#main");
  if (!data.guide) {
    main.replaceChildren(el("p", { class: "empty" },
      "Noch kein Leitfaden. ", el("a", { href: pHref("/setup") }, "Leitfaden eingeben →")));
    return;
  }
  if (!data.interviews.length) {
    main.replaceChildren(el("p", { class: "empty" },
      "Noch keine fertigen Interviews. ", el("a", { href: pHref("/setup") }, "Aufnahme hochladen →")));
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
      el("a", { href: iHref(id) }, id),
      el("div", { class: "meta" }, fmt(iv.duration_s), iv.has_audio ? "" : " · kein Audio",
        iv.has_roles ? "" : " · Rollen unbekannt"),
      iv.guide_mismatch ? el("div", { class: "meta warn" }, "mit älterem Leitfaden analysiert – ",
        el("a", { href: pHref("/setup") }, "neu analysieren")) : null));
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
  node.append(el("a", { class: "icon time", href: iHref(id, t.turn), title: "im Transkript öffnen" }, " ⤴"));
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
      el("a", { class: "icon time", href: iHref(id, lk.turn), title: "im Transkript öffnen" }, "⤴")),
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
      el("a", { class: "icon time", href: iHref(id, s.turn), title: "im Transkript öffnen" }, "⤴")),
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
        target !== undefined ? el("a", { href: iHref(id, target) }, STATUS_LABEL[c.status], first ? ` ${fmt(first.start)}` : "")
          : STATUS_LABEL[c.status]));
  }
  side.append(cov,
    el("h3", {}, "Bedienung"),
    el("div", { class: "legend" },
      el("p", {}, "Text mit der Maus markieren → „Als Frage markieren“ oder „Antwort auf …“."),
      el("p", {}, "Auf ein Wort klicken → Audio springt dorthin."),
      el("p", {}, el("span", { class: "tag" }, "F1"), "Frage  ", el("span", { class: "tag link" }, "↗F3"), "beantwortet auch F3  ",
        el("span", { class: "w low" }, "unsicher"))));

  const header = el("div", { class: "toolbar" }, el("a", { href: pHref() }, "← Vergleich"), el("strong", {}, `Interview ${id}`),
    iv?.has_audio ? null : el("span", { class: "warn" }, "Keine Audiodatei hinterlegt."));
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
