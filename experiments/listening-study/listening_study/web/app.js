"use strict";
const $ = id => document.getElementById(id);
const roles = ["source", "left", "right"];
let bundle = null, response = null, index = 0, heard = {}, elapsed = {}, previous = {};
let loading = false, initialized = false, collecting = false, config = null, savedState = null;
async function api(path, data) {
  const options = {cache: "no-store", credentials: "same-origin"};
  if (data !== undefined) Object.assign(options, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
  const reply = await fetch("/api/" + path, options);
  if (!reply.ok) {
    const data = await reply.json().catch(() => ({}));
    const error = new Error("request failed");
    error.publicMessage = {closed: "Набор в это исследование завершён. Существующую сессию ещё можно открыть для проверки или удаления.",
      full: "Сейчас все места заняты. Попробуй вернуться позже; новая сессия не создана.",
      busy: "Слишком много запросов. Подожди минуту и повтори попытку."}[data.error];
    throw error;
  }
  return reply.json();
}
async function action(work) {
  if (loading) return;
  loading = true;
  for (const b of document.querySelectorAll("button")) b.disabled = true;
  try { await work(); }
  catch (error) { $("status").textContent = error.publicMessage || "Сервер не подтвердил действие. Проверь соединение и повтори попытку. Можно обновить страницу: подтверждённые ответы сохранятся."; }
  finally {
    loading = false;
    for (const b of document.querySelectorAll("button")) b.disabled = false;
    $("start").disabled = !initialized || !$("consent").checked;
    updateButtons();
  }
}
function credits(state) {
  $("credits").hidden = !state.credits;
  $("credits-text").textContent = (state.credits || []).join("\n\n");
  $("reward").hidden = !state.surveycircle_code;
  $("reward-code").textContent = state.surveycircle_code || "";
}
function accept(state) {
  $("status").textContent = "";
  savedState = state;
  credits(state);
  if (["withdrawn", "expired", "unavailable"].includes(state.status)) {
    stopAudio(true); response = bundle = null;
    $("exit-copy").textContent = state.status === "withdrawn" ? "Ответы удалены с сервера. Повторная отправка этой сессии закрыта." : "Сессия недоступна или срок хранения истёк. Ответы этой сессии восстановить нельзя.";
    $("recovery-card").hidden = true; show("withdrawn"); return;
  }
  bundle = state.bundle; response = state.response; index = response.answers.length;
  if (state.recovery_code) {
    $("recovery-code").textContent = state.recovery_code; $("recovery-card").hidden = false;
  }
  render();
}

async function loadBundle() {
  const embedded = $("embedded-study");
  if (embedded) return JSON.parse(embedded.textContent);
  const result = await fetch("/session", {cache: "no-store"});
  if (!result.ok) throw new Error("session unavailable");
  return result.json();
}

function show(id) {
  for (const name of ["welcome", "trial", "finished", "withdrawn", "resume"]) $(name).hidden = name !== id;
  $("restore-card").hidden = !collecting || !["welcome", "resume"].includes(id);
}
function stopAudio(clear = false) {
  for (const role of roles) {
    $(role).pause();
    if (clear) { $(role).removeAttribute("src"); $(role).load(); }
  }
}
async function withdraw() {
  if (collecting && savedState && savedState.status !== "new") {
    await action(async () => { stopAudio(); accept(await api("withdraw", {})); });
    return;
  }
  if (loading) return;
  stopAudio(true);
  response = null; bundle = null; heard = {}; elapsed = {}; previous = {};
  show("withdrawn"); $("status").textContent = ""; $("exit-title").focus();
}
function updateButtons() {
  const ready = roles.every(role => heard[role]);
  for (const id of ["choose-left", "choose-right", "neither"]) $(id).disabled = !ready;
}
function render() {
  stopAudio();
  if (index === bundle.trials.length) {
    stopAudio(true);
    if (collecting) {
      const done = response.status === "complete";
      $("finish-copy").textContent = done ? "Ответы сохранены. Спасибо! Файл скачивать и пересылать не нужно." : "Все задания пройдены. Ответы сохранены как незавершённая сессия. Подтверди завершение, чтобы включить их в исследование.";
      $("submit").hidden = done; $("download").hidden = true; $("download-hint").hidden = true;
    } else { response.status = "complete"; }
    show("finished"); $("finish-title").focus(); return;
  }
  const trial = bundle.trials[index];
  heard = {}; elapsed = {}; previous = {};
  for (const role of roles) {
    heard[role] = false; elapsed[role] = 0; previous[role] = 0;
    $(role).src = trial[role]; $(role).load(); $("heard-" + role).textContent = "Ещё не прослушан";
  }
  $("progress-text").textContent = `Задание ${index + 1} из ${bundle.trials.length}`;
  $("progress").max = bundle.trials.length; $("progress").value = index;
  $("question").textContent = bundle.prompt; $("status").textContent = "";
  updateButtons(); show("trial"); $("question").focus();
}
$("consent").addEventListener("change", () => { $("start").disabled = !initialized || !$("consent").checked; });
$("start").addEventListener("click", async () => {
  if (!initialized || !$("consent").checked || loading) return;
  if (collecting) {
    await action(async () => { accept(await api("start", {consent: true, consent_version: config.consent_version})); });
    return;
  }
  loading = true; $("start").disabled = true;
  try {
    const data = await loadBundle();
    if (!$("withdrawn").hidden) return;
    bundle = data;
    response = Object.fromEntries(["schema", "study_id", "study_sha256", "demo", "phase", "slot", "prompt_id"].map(k => [k, bundle[k]]));
    response.participant_id = crypto.randomUUID(); response.status = "in_progress"; response.answers = [];
    index = 0; render();
  } catch {
    $("status").textContent = "Не удалось открыть исследование. Проверь локальный сервер и попробуй ещё раз.";
    $("start").disabled = !$("consent").checked;
  } finally { loading = false; }
});
for (const role of roles) {
  const audio = $(role);
  audio.addEventListener("play", () => { for (const other of roles) if (other !== role) $(other).pause(); });
  audio.addEventListener("seeking", () => { previous[role] = audio.currentTime; });
  audio.addEventListener("ratechange", () => { if (audio.playbackRate !== 1) audio.playbackRate = 1; });
  audio.addEventListener("timeupdate", () => {
    if (!response || $("trial").hidden || audio.seeking) return;
    const delta = audio.currentTime - previous[role];
    previous[role] = audio.currentTime;
    if (delta > 0 && delta < .8) elapsed[role] += delta;
    if (elapsed[role] >= 5) heard[role] = true;
    $("heard-" + role).textContent = heard[role] ? "✓ Можно выбрать" : `Прослушано ${Math.floor(elapsed[role])} из 5 секунд`;
    updateButtons();
  });
  audio.addEventListener("error", () => {
    if (response && !$("trial").hidden) $("status").textContent = "Не удалось воспроизвести отрывок. Можно повторить попытку или пропустить задание.";
  });
}
for (const button of document.querySelectorAll("[data-choice]")) {
  button.addEventListener("click", async () => {
    if (!response || $("trial").hidden || button.disabled) return;
    const answer = {trial_id: bundle.trials[index].id, choice: button.dataset.choice, heard: {...heard}};
    if (collecting) {
      await action(async () => {
        stopAudio();
        accept(await api("answer", {index, answer}));
        $("status").textContent = "Ответ сохранён на сервере.";
      });
    } else { response.answers.push(answer); index++; render(); }
  });
}
for (const id of ["decline", "withdraw", "discard"]) $(id).addEventListener("click", withdraw);
$("download").addEventListener("click", () => {
  if (!response || response.status !== "complete") return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(response, null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url;
  link.download = `listening-${response.demo ? "demo-" : ""}${response.participant_id}.json`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  $("status").textContent = "Файл подготовлен к сохранению. Передача исследователю — только по твоему решению.";
});
$("submit").addEventListener("click", () => action(async () => { accept(await api("complete", {})); }));
$("continue").addEventListener("click", () => action(async () => { accept(await api("state")); }));
$("resume-withdraw").addEventListener("click", withdraw);
$("restore").addEventListener("click", () => action(async () => {
  const state = await api("resume", {code: $("restore-code").value.trim()});
  $("restore-code").value = ""; accept(state);
}));
// A read before consent neither allocates a seat nor creates a cookie. Existing consent may be resumed explicitly.
loadBundle().then(async data => {
  $("demo").hidden = !data.demo;
  if (!data.collection) { initialized = true; $("decline").disabled = false; $("start").disabled = !$("consent").checked; return; }
  collecting = true; config = data;
  $("privacy-copy").textContent = `После согласия каждый ответ сохраняется на сервере под случайным кодом. Нужен только cookie для продолжения и защиты от повторной отправки; имена, IP-адреса, аккаунты и данные устройства в базу не записываются. Сеть и хостинг технически обрабатывают IP при соединении. Незавершённые ответы удаляются на седьмой календарный день UTC после начала, остальные — ${config.delete_on} (UTC). Отказ удаляет ответы сразу; минимальная отметка об отказе без ответов остаётся до этой даты. Закрытие вкладки не означает отказ: вернись в том же браузере или используй резервный код. Доступ к ответам — у исследователя; публикуются только сводные результаты. Контакт: ${config.contact}.`;
  $("restore-card").hidden = false;
  const state = await api("state");
  initialized = true; $("decline").disabled = false; $("start").disabled = !$("consent").checked;
  if (state.status !== "new") {
    savedState = state;
    if (["in_progress", "complete"].includes(state.status)) show("resume");
    else accept(state);
  }
}).catch(() => { $("start").disabled = true; $("status").textContent = "Исследование недоступно. Обнови страницу позже."; });
window.addEventListener("pagehide", () => { stopAudio(true); response = null; bundle = null; });
window.addEventListener("pageshow", event => { if (event.persisted) location.reload(); });
