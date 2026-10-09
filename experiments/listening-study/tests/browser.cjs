/* Real Chromium checks; no mocked playback, listener data or account access. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {spawn} = require("node:child_process");
const http = require("node:http");
const {pathToFileURL} = require("node:url");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const demo = path.resolve(process.argv[2] || "work/demo");
const output = path.resolve(process.argv[3] || "work/browser");
fs.mkdirSync(output, {recursive: true});
const checks = [], errors = [], outbound = [];
const base = "http://127.0.0.1:8765";
let browser, server;
async function visible(page, id) { await page.locator(id).waitFor({state: "visible"}); }
async function start(page, url) {
  await page.goto(url);
  await visible(page, "#demo");
  assert.equal(await page.locator("#start").isDisabled(), true);
  await page.locator("#consent").check();
  await page.locator("#start").click();
  await visible(page, "#trial");
}
async function listen(page) {
  for (const role of ["source", "left", "right"]) {
    await page.locator("#" + role).evaluate(a => a.play());
    await page.waitForFunction(r => document.getElementById("heard-" + r).textContent.includes("✓"), role, {timeout: 12000});
    await page.locator("#" + role).evaluate(a => a.pause());
  }
}
async function pageFor(viewport = {width: 1200, height: 1000}) {
  const page = await browser.newPage({viewport});
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", msg => { if (msg.type() === "error") errors.push(msg.text()); });
  await page.route("**/*", route => {
    const url = route.request().url();
    if (/^(file:|data:|blob:)/.test(url) || url.startsWith(base + "/")) return route.continue();
    outbound.push(url); return route.abort();
  });
  return page;
}
(async () => {
  server = spawn(process.env.STUDY_PYTHON || "python3", ["-m", "listening_study", "serve", path.join(demo, "study.json"), "--slot", "0", "--question", "next"], {stdio: ["ignore", "pipe", "pipe"]});
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Loopback server startup timed out")), 10000);
    server.stdout.once("data", () => {clearTimeout(timer); resolve();});
    server.once("exit", code => {clearTimeout(timer); reject(new Error("Loopback server exited: " + code));});
  });
  browser = await chromium.launch({headless: true});
  const page = await pageFor();
  await page.goto(base);
  await visible(page, "#demo");
  await page.screenshot({path: path.join(output, "welcome.png"), fullPage: true});
  await start(page, base);
  await page.screenshot({path: path.join(output, "comparison.png"), fullPage: true});
  assert.match(await page.locator("#question").textContent(), /сохранить текущий настрой/);
  assert.equal(await page.locator("#choose-left").isDisabled(), true);
  const session = await (await fetch(base + "/session")).json();
  const privateWords = /demo_group|synthetic_d|artist_id|genre|first_left|rights|source_sha256/;
  assert.equal(privateWords.test(JSON.stringify(session)), false);
  assert.equal(privateWords.test(await page.locator("body").innerText()), false);
  await page.locator("#source").evaluate(a => a.play());
  await page.locator("#left").evaluate(a => a.play());
  assert.equal(await page.locator("#source").evaluate(a => a.paused), true);
  await page.locator("#left").evaluate(a => a.pause());
  await listen(page);
  assert.equal(await page.locator("#choose-left").isDisabled(), false);
  await page.locator("#choose-left").click();
  assert.equal(await page.locator("#progress-text").textContent(), "Задание 2 из 8");
  await listen(page);
  await page.locator("#neither").click();
  for (let i = 2; i < 8; i++) await page.locator("#skip").click();
  await visible(page, "#finished");
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#download").click();
  const download = await downloadEvent;
  const responseFile = path.join(output, "browser-response.json");
  await download.saveAs(responseFile);
  const response = JSON.parse(fs.readFileSync(responseFile));
  assert.deepEqual(response.answers.map(a => a.choice), ["left", "neither", "skip", "skip", "skip", "skip", "skip", "skip"]);
  assert.equal(response.demo, true); assert.equal(response.status, "complete");
  assert.deepEqual(Object.keys(response).sort(), ["schema", "study_id", "study_sha256", "demo", "phase", "slot", "prompt_id", "participant_id", "status", "answers"].sort());
  assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
  assert.equal((await page.context().cookies()).length, 0);
  await page.locator("#discard").click();
  await visible(page, "#withdrawn");
  assert.equal(await page.evaluate(() => document.querySelectorAll("audio[src]").length), 0);
  checks.push("consent", "actual WAV playback", "exclusive playback", "listening gate", "blind payload/DOM", "choice/neither/skip", "voluntary JSON export", "no browser storage/cookies", "withdrawal after export");
  const mobile = await pageFor({width: 390, height: 844});
  await start(mobile, base);
  assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await mobile.screenshot({path: path.join(output, "mobile.png"), fullPage: true});
  await mobile.locator("#withdraw").click();
  await visible(mobile, "#withdrawn");
  checks.push("mobile layout", "mid-session withdrawal");
  const offline = await pageFor();
  await start(offline, pathToFileURL(path.join(demo, "demo-similarity.html")).href);
  assert.match(await offline.locator("#question").textContent(), /в целом больше похожа/);
  await offline.locator("#source").evaluate(a => a.play());
  await offline.waitForFunction(() => document.getElementById("source").currentTime > .5);
  await offline.locator("#withdraw").click();
  await visible(offline, "#withdrawn");
  await offline.goto(pathToFileURL(path.join(demo, "demo-next.html")).href);
  await offline.locator("#decline").click();
  await visible(offline, "#withdrawn");
  checks.push("portable file demo + embedded audio", "separate similarity wording", "decline before consent");
  for (const url of ["/study.json", "/../study.json", "/responses", "/raw/anything.wav"]) assert.equal((await fetch(base + url)).status, 404);
  assert.equal((await fetch(base + "/session", {headers: {Origin: "https://example.org"}})).status, 403);
  // Fetch owns the Host header; use HTTP's raw header API for this negative probe.
  const wrongHost = await new Promise((resolve, reject) => {
    http.get(base + "/session", {headers: {Host: "example.org"}}, reply => {
      reply.resume(); resolve(reply.statusCode);
    }).on("error", reject);
  });
  assert.equal(wrongHost, 403);
  assert.equal((await fetch(base + "/responses", {method: "POST", body: "do not store"})).status, 501);
  const audioReply = await fetch(base + session.trials[0].source);
  assert.equal(audioReply.headers.get("content-type"), "audio/wav");
  assert.equal(audioReply.headers.get("cache-control"), "no-store");
  checks.push("loopback HTTP allowlist + origin/host checks", "no response POST handler", "no-store audio");
  assert.deepEqual(outbound, []); assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, "browser-checks.json"), JSON.stringify({demo: true, browser: await browser.version(), checks, externalRequests: outbound.length, pageErrors: errors}, null, 2));
  console.log(`PASS: ${checks.length} browser/HTTP checks; no external requests or page errors`);
})().catch(e => {console.error(e); process.exitCode = 1;}).finally(async () => {
  if (browser) await browser.close();
  if (server) server.kill("SIGTERM");
});
