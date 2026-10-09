"use strict";
(() => {
  const data = JSON.parse(document.getElementById("review-data").textContent);
  const tracks = new Map(data.tracks.map(t => [t.id, t]));
  const pairMap = new Map(data.pairs.map(p => [p.source + ":" + p.candidate, p]));
  const key = "yanjaro-research-review:" + data.review_sha256 + ":" + data.reviewer;
  const $ = id => document.getElementById(id);
  const decisions = {pending: "Не проверено", fit: "Подходит", unfit: "Не подходит", uncertain: "Сомнительно"};
  const relations = {unknown: "Не оценено / неизвестно", near: "Близко", far: "Различается", uncertain: "Сомнительно"};
  const trackDefaults = () => ({perceived_bpm: null, tempo_note: "", rhythm_note: "", energy_note: "", instruments: "", genre: "", artifacts: "", bpm_wrong: false, decision: "pending", reason: ""});
  const pairDefaults = () => ({tempo_relation: "unknown", rhythm_relation: "unknown", energy_relation: "unknown", instrument_relation: "unknown", genre_relation: "unknown", similarity_wrong: false, decision: "pending", reason: ""});
  let state = {schema: data.schema, review_sha256: data.review_sha256, catalog_sha256: data.catalog_sha256,
    reviewer: data.reviewer, demo: data.demo, status: "PROVISIONAL", tracks: {}, pairs: {}};
  function validate(value) {
    const keys = Object.keys(state).sort().join();
    if (!value || Object.keys(value).sort().join() !== keys) throw Error("Неизвестный формат JSON");
    for (const k of ["schema", "review_sha256", "catalog_sha256", "reviewer", "demo", "status"])
      if (value[k] !== state[k]) throw Error("JSON относится к другому проверяющему или набору отрывков");
    for (const [group, defaults, allowed] of [["tracks", trackDefaults, tracks], ["pairs", pairDefaults, pairMap]]) {
      if (!value[group] || Array.isArray(value[group]) || typeof value[group] !== "object") throw Error("Повреждённые оценки");
      for (const [id, row] of Object.entries(value[group])) {
        if (!allowed.has(id) || !row || Object.keys(row).sort().join() !== Object.keys(defaults()).sort().join()) throw Error("Неизвестная запись или поле");
        for (const [name, v] of Object.entries(row)) {
          if (name === "perceived_bpm") {
            if (v !== null && (typeof v !== "number" || !Number.isFinite(v) || v < 20 || v > 500)) throw Error("BPM должен быть 20–500 или пустым");
          } else if (name === "decision") {
            if (!Object.hasOwn(decisions, v)) throw Error("Неизвестное решение");
          } else if (name.endsWith("_relation")) {
            if (!Object.hasOwn(relations, v)) throw Error("Неизвестная оценка сходства");
          } else if (name.endsWith("_wrong")) {
            if (typeof v !== "boolean") throw Error("Некорректная отметка ошибки");
          } else if (typeof v !== "string" || v.length > 2000) throw Error("Слишком длинная или некорректная заметка");
        }
      }
    }
    return value;
  }
  function save() {
    try {
      validate(state);
      localStorage.setItem(key, JSON.stringify(state));
      $("save-status").textContent = "Черновик сохранён в этом браузере. Для резервной копии сохраните JSON.";
    } catch (error) {
      $("save-status").textContent = "Черновик только в памяти страницы: " + error.message + ". Сохраните JSON до закрытия.";
    }
  }
  try {
    const old = localStorage.getItem(key);
    if (old) { state = validate(JSON.parse(old)); $("save-status").textContent = "Восстановлен ваш локальный черновик."; }
    else $("save-status").textContent = "Оценок пока нет. Сохраните JSON перед закрытием.";
  } catch (error) { $("save-status").textContent = "Локальный черновик недоступен: " + error.message + ". Используйте JSON."; }
  function el(tag, text, parent) {
    const node = document.createElement(tag); if (text !== undefined) node.textContent = text;
    if (parent) parent.append(node); return node;
  }
  function selector(parent, label, options, value, change) {
    const wrapper = el("label", label, parent), input = el("select", undefined, wrapper);
    for (const [id, name] of Object.entries(options)) { const option = el("option", name, input); option.value = id; }
    input.value = value; input.addEventListener("change", () => change(input.value)); return input;
  }
  const labels = Object.fromEntries(data.tracks.map(t => [t.id, t.id + " · " + t.title + " — " + t.artist]));
  function audio(id, parent) { const a = el("audio", undefined, parent); a.controls = true; a.preload = "none"; a.src = data.audio[id]; a.setAttribute("aria-label", labels[id]); }
  document.addEventListener("play", event => {
    if (event.target.tagName === "AUDIO") for (const a of document.querySelectorAll("audio")) if (a !== event.target) a.pause();
  }, true);
  function details(parent, title, value) { const d = el("details", undefined, parent); el("summary", title, d); el("pre", JSON.stringify(value, null, 2), d); }
  function inputField(parent, row, name, label, type = "text") {
    const wrapper = el("label", label, parent);
    const input = el(type === "text" ? "textarea" : "input", undefined, wrapper);
    input.dataset.field = name;
    if (type === "checkbox") { input.type = type; input.checked = row[name]; }
    else if (type === "number") { input.type = type; input.min = "20"; input.max = "500"; input.step = "0.1"; input.value = row[name] ?? ""; }
    else { input.maxLength = 2000; input.value = row[name]; }
    input.addEventListener("input", () => {
      if (type === "number" && !input.checkValidity()) { $("error").textContent = "Введите BPM от 20 до 500 или оставьте поле пустым."; return; }
      row[name] = type === "checkbox" ? input.checked : type === "number" ? (input.value === "" ? null : Number(input.value)) : input.value;
      $("error").textContent = ""; save();
    });
  }
  function decision(parent, row) {
    const select = selector(parent, "Решение", decisions, row.decision, value => { row.decision = value; save(); });
    select.dataset.field = "decision";
    inputField(parent, row, "reason", "Причина решения / сомнения (обязательно для итогового решения)");
  }
  $("identity").textContent = data.reviewer + " · " + (data.demo ? "DEMO: синтетический тест" : "Реальные записи") + " · набор " + data.review_sha256.slice(0, 12);
  const counts = Object.fromEntries("ABCD".split("").map(c => [c, data.pairs.filter(p => p.condition === c).length]));
  $("pool-status").textContent = `${data.tracks.length} отрывков. Направленные пары A/B/C/D: ${Object.values(counts).join(" / ")}. Строгих вариантов троек: ${data.trials.options.length}; без повторов в предварительном наборе: ${data.trials.disjoint_preview.length}.`;
  const slots = [data.tracks[0].id];
  for (let i = 1; i < 3; i++) slots.push(data.tracks.find(t => !slots.includes(t.id) && slots.every(id => tracks.get(id).artist_id !== t.artist_id))?.id || data.tracks.find(t => !slots.includes(t.id)).id);
  const selects = [];
  for (let i = 0; i < 3; i++) selects.push(selector($("selectors"), ["Источник", "Кандидат 1", "Кандидат 2"][i], labels, slots[i], value => {
    slots[i] = value; $("proposal").value = "manual"; renderComparison();
  }));
  const proposals = {manual: "Диагностическое сравнение — не отобранная тройка"};
  data.trials.disjoint_preview.forEach((t, i) => { proposals[i] = `${t.kind === "primary" ? "A/B" : "C/D"}: ${t.source} + ${t.first} + ${t.second} · PROVISIONAL`; });
  for (const [id, text] of Object.entries(proposals)) { const option = el("option", text, $("proposal")); option.value = id; }
  $("proposal").value = "manual";
  $("proposal").addEventListener("change", () => {
    if ($("proposal").value !== "manual") {
      const t = data.trials.disjoint_preview[Number($("proposal").value)];
      [t.source, t.first, t.second].forEach((id, i) => { slots[i] = id; selects[i].value = id; });
    }
    renderComparison();
  });
  function renderComparison() {
    for (const a of $("players").querySelectorAll("audio")) a.pause();
    $("players").replaceChildren(); $("comparisons").replaceChildren();
    const valid = new Set(slots).size === 3 && new Set(slots.map(id => tracks.get(id).artist_id)).size === 3 &&
      new Set(slots.map(id => tracks.get(id).source_sha256)).size === 3 && new Set(slots.map(id => tracks.get(id).clip_sha256)).size === 3;
    $("comparison-status").textContent = !valid ? "Это сочетание исключено: повтор записи или авторской группы. Прослушивание доступно; оценка тройки отключена." :
      $("proposal").value === "manual" ? "Свободное диагностическое сравнение. Оно не добавляется к алгоритмическим тройкам и не меняет пороги." : "Предварительная тройка PROVISIONAL; требуется независимая ручная проверка.";
    slots.forEach((id, i) => {
      const t = tracks.get(id), card = el("article", undefined, $("players")); card.className = "card";
      el("h3", ["Источник", "Кандидат 1", "Кандидат 2"][i] + " · " + t.title, card); el("p", t.artist, card); audio(id, card);
      el("small", `${t.start.toFixed(3)}–${(t.start + t.seconds).toFixed(3)} с · оценка BPM ${t.features.bpm?.toFixed(1) ?? "неизвестно"} · альтернативы ${t.features.bpm_alternatives.map(x => x.toFixed(1)).join(" / ") || "неизвестно"}`, card);
      details(card, "Измерения и источники тегов", {features: t.features, raw_features: t.raw_features, gain_db: t.gain_db, genre: t.genre, instrument: t.instrument,
        genre_source: t.genre_source, instrument_source: t.instrument_source, publication_hints: t.tag_hints, attribution: t.attribution});
    });
    if (!valid) return;
    for (const id of slots.slice(1)) {
      const pairKey = slots[0] + ":" + id, p = pairMap.get(pairKey);
      if (!p) continue;
      const card = el("article", undefined, $("comparisons")); card.className = "card"; card.dataset.pair = pairKey;
      el("h3", slots[0] + " → " + id + " · " + (p.condition || "Условие не установлено"), card);
      el("p", p.reason, card); details(card, "Дистанции screen-v1", p);
      const row = state.pairs[pairKey] ||= pairDefaults();
      for (const [name, label] of [["tempo_relation", "Ощущаемый темп"], ["rhythm_relation", "Ритм"], ["energy_relation", "Энергия"], ["instrument_relation", "Инструментовка"], ["genre_relation", "Жанр"]]) {
        const select = selector(card, label, relations, row[name], value => { row[name] = value; save(); }); select.dataset.field = name;
      }
      inputField(card, row, "similarity_wrong", "Алгоритм неверно описывает музыкальное сходство", "checkbox"); decision(card, row);
    }
  }
  for (const [id, label] of Object.entries(labels)) { const option = el("option", label, $("track")); option.value = id; }
  function renderTrack() {
    for (const a of $("track-form").querySelectorAll("audio")) a.pause();
    $("track-form").replaceChildren(); const id = $("track").value;
    const row = state.tracks[id] ||= trackDefaults(); audio(id, $("track-form"));
    inputField($("track-form"), row, "perceived_bpm", "Ощущаемый BPM (пусто = неизвестно)", "number");
    inputField($("track-form"), row, "bpm_wrong", "BPM алгоритма неверен / требует другого уровня пульса", "checkbox");
    for (const [name, label] of [["tempo_note", "Темп и half-time / double-time"], ["rhythm_note", "Ритм: атаки, пульс, регулярность"], ["energy_note", "Ощущаемая энергия и динамика"], ["instruments", "Слышимые инструменты (только положительные наблюдения)"], ["genre", "Жанровая оценка / неизвестно"], ["artifacts", "Тишина, клиппинг, щелчки, голос, обрыв или другие проблемы"]]) inputField($("track-form"), row, name, label);
    decision($("track-form"), row);
  }
  $("track").addEventListener("change", renderTrack);
  $("export").addEventListener("click", () => {
    try {
      validate(state);
      if ([...document.querySelectorAll('input[type="number"]')].some(input => !input.checkValidity())) throw Error("Исправьте BPM или оставьте поле пустым перед сохранением.");
      if ([...Object.values(state.tracks), ...Object.values(state.pairs)].some(r => r.decision !== "pending" && r.reason.trim().length < 3)) throw Error("Укажите причину каждого решения (не менее 3 символов) либо оставьте «Не проверено».");
      const blob = new Blob([JSON.stringify(state, null, 2) + "\n"], {type: "application/json"});
      const url = URL.createObjectURL(blob), a = el("a"); a.href = url; a.download = `${data.reviewer}-${data.review_sha256.slice(0, 12)}.json`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000); $("error").textContent = "";
      $("save-status").textContent = "JSON подготовлен для сохранения браузером. Проверьте файл в загрузках.";
    } catch (error) { $("error").textContent = error.message; }
  });
  $("import").addEventListener("change", async event => {
    try {
      const file = event.target.files[0]; if (!file) return;
      if (file.size > 1024 * 1024) throw Error("JSON больше 1 МиБ");
      state = validate(JSON.parse(await file.text())); renderTrack(); renderComparison(); save(); $("error").textContent = "";
    } catch (error) { $("error").textContent = error.message; }
    event.target.value = "";
  });
  renderComparison(); renderTrack();
})();
