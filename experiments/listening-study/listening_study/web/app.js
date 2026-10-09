"use strict";
const $ = id => document.getElementById(id);
const roles = ["source", "left", "right"];
let bundle = null, response = null, index = 0, heard = {}, elapsed = {}, previous = {};
let loading = false;

async function loadBundle() {
  const embedded = $("embedded-study");
  if (embedded) return JSON.parse(embedded.textContent);
  const result = await fetch("/session", {cache: "no-store"});
  if (!result.ok) throw new Error("session unavailable");
  return result.json();
}

function show(id) {
  for (const name of ["welcome", "trial", "finished", "withdrawn"]) $(name).hidden = name !== id;
}
function stopAudio(clear = false) {
  for (const role of roles) {
    $(role).pause();
    if (clear) { $(role).removeAttribute("src"); $(role).load(); }
  }
}
function withdraw() {
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
    stopAudio(true); response.status = "complete"; show("finished"); $("finish-title").focus(); return;
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
$("consent").addEventListener("change", () => { $("start").disabled = !$("consent").checked; });
$("start").addEventListener("click", async () => {
  if (!$("consent").checked || loading) return;
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
  button.addEventListener("click", () => {
    if (!response || $("trial").hidden || button.disabled) return;
    response.answers.push({trial_id: bundle.trials[index].id, choice: button.dataset.choice, heard: {...heard}});
    index++; render();
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
// Read only the demo label before consent. No participant is allocated, no audio fetched.
loadBundle()
  .then(data => { $("demo").hidden = !data.demo; })
  .catch(() => { $("status").textContent = "Исследование недоступно. Проверь локальный сервер."; });
window.addEventListener("pagehide", () => { stopAudio(true); response = null; bundle = null; });
