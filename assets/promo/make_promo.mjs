#!/usr/bin/env node
// Records the promo video: drives the Lifelog in headless Chrome and films it.
//
//   node assets/promo/make_promo.mjs           the full walk-through, limitful-promo.mp4
//   node assets/promo/make_promo.mjs --short   the 37-second launch cut, limitful-launch.mp4
//
// Both have music under them (launch-music.ogg); the launch cut's opening cards are timed to its beat.
// Needs node 22+, uv, ffmpeg and Google Chrome. Everything on screen is made up:
// the app is served by pretend_server.py, which stands in for the pendant, the
// speech model and Ask, and fills the Lifelog with the `limitful demo` conversations.
// Writes limitful-promo.mp4 and poster.jpg next to this file.
//
// Settings, all optional, from the environment:
//   PROMO_WORK         folder for frames and the scratch data (default: a new temp folder)
//   PROMO_PORT         port for the pretend server (default 4811)
//   PROMO_CHROME_PORT  Chrome's debugging port (default 9344)
//   CHROME             path to the Chrome binary

import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const work = process.env.PROMO_WORK ? resolve(process.env.PROMO_WORK) : mkdtempSync(join(tmpdir(), "limitful-promo-"));
const port = Number(process.env.PROMO_PORT || 4811);
const chromePort = Number(process.env.PROMO_CHROME_PORT || 9344);
const chrome = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const SHORT = process.argv.includes("--short");
const WIDTH = 1280, HEIGHT = 720, SCALE = 1.5;  // filmed at 1920 x 1080; any narrower and the app's header wraps
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// The launch cut plays 1.25 times faster than it is filmed, over music at 117.5 beats a minute.
const SPEED = Number(process.env.PROMO_SPEED || (SHORT ? 1.25 : 1.12));
const BEAT = (60000 / 117.5) * SPEED;  // one beat of the music, in filming time

for (const dir of ["data", "frames", "chrome"]) rmSync(join(work, dir), { recursive: true, force: true });
mkdirSync(join(work, "data"), { recursive: true });
mkdirSync(join(work, "frames"), { recursive: true });
// Its own settings file, so no saved key or choice of the person running this is read or shown.
// The short cut goes straight to Ask, which needs Claude chosen; the answer comes from pretend_server.py.
writeFileSync(join(work, "config.json"), SHORT ? JSON.stringify({ provider: "claude" }) : "{}");

const children = [];
const stop = () => { for (const child of children) { try { child.kill(); } catch { /* already gone */ } } };
process.on("exit", stop);
process.on("SIGINT", () => process.exit(1));

const server = spawn("uv", ["run", "python", join(here, "pretend_server.py"), join(work, "data"), String(port), ...(SHORT ? ["ready"] : [])], {
  cwd: repo, env: { ...process.env, LIMITFUL_CONFIG: join(work, "config.json") }, stdio: ["ignore", "inherit", "inherit"],
});
children.push(server);
const browser = spawn(chrome, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--autoplay-policy=no-user-gesture-required",
  `--remote-debugging-port=${chromePort}`, `--user-data-dir=${join(work, "chrome")}`, `--window-size=${WIDTH},${HEIGHT}`, "about:blank",
], { stdio: "ignore" });
children.push(browser);

const reachable = async (url) => { try { return (await fetch(url)).ok; } catch { return false; } };
for (let i = 0; i < 240 && !(await reachable(`http://127.0.0.1:${port}/api/days`)); i++) await sleep(250);
let target;
for (let i = 0; i < 80 && !target; i++) {
  try { target = (await (await fetch(`http://127.0.0.1:${chromePort}/json`)).json()).find((t) => t.type === "page"); } catch { await sleep(250); }
}
if (!target) throw new Error("Chrome did not start");

// --- a small DevTools client ------------------------------------------------------
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0;
const waiting = new Map();
const frames = [];  // { at: seconds, file }
ws.addEventListener("message", (m) => {
  const d = JSON.parse(m.data);
  if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); return; }
  if (d.method === "Page.screencastFrame") {
    const file = join(work, "frames", `${String(frames.length).padStart(6, "0")}.jpg`);
    writeFileSync(file, Buffer.from(d.params.data, "base64"));
    frames.push({ at: d.params.metadata.timestamp, file });
    ws.send(JSON.stringify({ id: ++seq, method: "Page.screencastFrameAck", params: { sessionId: d.params.sessionId } }));
  }
});
const send = (method, params = {}) => new Promise((r) => { const id = ++seq; waiting.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const run = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true, userGesture: true });
  if (r.result.exceptionDetails) throw new Error(`${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}\n  in: ${expression.slice(0, 200)}`);
  return r.result.result.value;
};
const until = async (expression, timeout = 20000) => {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await run(`Boolean(${expression})`)) return; await sleep(120); }
  throw new Error(`never became true: ${expression}`);
};

// --- what is drawn over the app: a pointer, captions and title cards ---------------
// The real wordmark, as drawn by assets/make_logo.py: dark ink on the light cards, cream on the dark ones.
const logo = readFileSync(join(repo, SHORT ? "assets/wordmark-dark.svg" : "assets/wordmark.svg"), "utf8").replace(/<title[^>]*>.*?<\/title>/, "").replace(/\s*aria-labelledby="t"/, "");
const overlay = `
(() => {
  const build = () => {
    if (window.__promo) return;
    document.documentElement.classList.toggle("promo-launch", __SHORT__);
    const style = document.createElement("style");
    style.textContent = \`
      #promo-cursor { position: fixed; left: 0; top: 0; z-index: 100000; pointer-events: none; width: 26px; height: 26px;
        transform: translate(600px, 430px); transition: transform 0.42s cubic-bezier(0.3, 0.1, 0.2, 1); filter: drop-shadow(0 2px 3px rgba(0,0,0,0.35)); }
      #promo-ring { position: fixed; z-index: 99999; pointer-events: none; width: 46px; height: 46px; margin: -23px 0 0 -23px;
        border-radius: 50%; border: 3px solid #f4c63a; background: rgba(244, 198, 58, 0.25); opacity: 0; }
      #promo-ring.go { animation: promo-ring 0.45s ease-out; }
      @keyframes promo-ring { from { opacity: 0.95; transform: scale(0.35); } to { opacity: 0; transform: scale(1.4); } }
      #promo-caption { position: fixed; left: 50%; bottom: 34px; z-index: 99998; pointer-events: none; width: max-content; max-width: 900px;
        transform: translate(-50%, 14px); opacity: 0; transition: opacity 0.3s, transform 0.3s, bottom 0.3s;
        background: #13201a; color: #eef2ef; font: 500 21px/1.35 "Avenir Next", "Segoe UI", system-ui, sans-serif;
        padding: 13px 26px; border-radius: 14px; text-align: center; box-shadow: 0 12px 32px rgba(19, 32, 26, 0.3); }
      #promo-caption.on { opacity: 1; transform: translate(-50%, 0); }
      #promo-caption.lift { bottom: 128px; }
      /* Beside a narrow page (the setup guide), where the bottom of the screen holds its buttons. */
      #promo-caption.beside { left: auto; right: 36px; bottom: auto; top: 300px; width: 262px; max-width: 262px; text-align: left;
        padding: 16px 20px; transform: translate(14px, 0); }
      #promo-caption.beside.on { transform: translate(0, 0); }
      #promo-card { position: fixed; inset: 0; z-index: 100001; background: #eef2ef; color: #13201a; display: grid; place-items: center;
        text-align: center; transition: opacity 0.5s; }
      #promo-card.off { opacity: 0; pointer-events: none; }
      #promo-card .lockup { display: flex; align-items: center; justify-content: center; gap: 22px; margin-bottom: 38px;
        font: 600 70px/1 "Avenir Next", "Segoe UI", system-ui, sans-serif; letter-spacing: -0.02em; }
      #promo-card .lockup svg { height: 112px; width: auto; }
      #promo-card h1 { margin: 0 auto 20px; max-width: 900px; font: 400 44px/1.2 "Charter", "Iowan Old Style", Georgia, serif; text-wrap: balance; }
      #promo-card p { margin: 0 auto; max-width: 760px; font: 400 23px/1.5 "Avenir Next", "Segoe UI", system-ui, sans-serif; color: #5e6e66; }
      #promo-card p.where { margin-top: 26px; color: #0b6b58; font-weight: 600; font-size: 27px; }
      #promo-card small { display: block; margin-top: 44px; font: 400 16px/1.4 "Avenir Next", "Segoe UI", system-ui, sans-serif; color: #5e6e66; }
      /* The launch cut: dark cards with big type, bigger captions, and no pointer. */
      .promo-launch #promo-card { background: #13201a; color: #eef2ef; transition: opacity 0.35s; }
      .promo-launch #promo-card h1 { max-width: 1060px; margin-bottom: 0; font: 600 78px/1.08 "Avenir Next", "Segoe UI", system-ui, sans-serif; letter-spacing: -0.03em; }
      .promo-launch #promo-card h1.gold { color: #f4c63a; }
      /* The opening line: light, so Limitless's own mark and the black pendant both read. */
      .promo-launch #promo-card:has(.hook) { background: #eef2ef; color: #13201a; }
      .promo-launch #promo-card .hook { display: flex; align-items: center; gap: 76px; text-align: left; }
      .promo-launch #promo-card .hook h1 { max-width: none; margin: 0; white-space: nowrap; }
      .promo-launch #promo-card .hook .theirs img { height: 0.92em; margin-right: 0.16em; vertical-align: -0.1em; }
      /* The photo is a square with the pendant inside it; the margins take the empty edges back. */
      .promo-launch #promo-card .hook .promo-pendant { height: 580px; margin: -30px -130px -30px -85px; filter: drop-shadow(0 26px 34px rgba(19, 32, 26, 0.3)); }
      .promo-launch #promo-card h1 + p { margin-top: 30px; }
      .promo-launch #promo-card p { color: #a9b8b0; font-size: 27px; max-width: 980px; }
      .promo-launch #promo-card p.where { color: #f4c63a; }
      .promo-launch #promo-card small { color: #7d8d85; }
      .promo-launch #promo-card .lockup { margin-bottom: 44px; }
      .promo-launch #promo-card.closing h1 { font-size: 58px; }
      .promo-launch #promo-card p.intro { margin-bottom: 30px; color: #f4c63a; font-weight: 600; font-size: 38px; letter-spacing: -0.01em; }
      .promo-launch #promo-card .late { opacity: 0; transition: opacity 0.4s; }
      .promo-launch #promo-card.more .late { opacity: 1; }
      .promo-launch #promo-caption { bottom: 46px; max-width: 1100px; background: #13201a; font: 600 36px/1.2 "Avenir Next", "Segoe UI", system-ui, sans-serif;
        letter-spacing: -0.015em; padding: 20px 38px; border-radius: 20px; box-shadow: 0 18px 50px rgba(19, 32, 26, 0.45); }
      .promo-launch #promo-caption.lift { bottom: 140px; }
      .promo-launch #promo-cursor, .promo-launch #promo-ring { display: none; }
      #promo-play { position: fixed; left: 50%; top: 50%; z-index: 100002; width: 132px; height: 132px; margin: -66px 0 0 -66px; border-radius: 50%;
        background: rgba(19, 32, 26, 0.86); display: grid; place-items: center; box-shadow: 0 14px 40px rgba(19, 32, 26, 0.35); }
      #promo-play::after { content: ""; margin-left: 10px; border-left: 44px solid #f4c63a; border-top: 27px solid transparent; border-bottom: 27px solid transparent; }
    \`;
    document.head.append(style);
    const make = (id, html = "") => { const node = document.createElement("div"); node.id = id; node.innerHTML = html; document.body.append(node); return node; };
    const cursor = make("promo-cursor", '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2.5v17l4.7-4.4 3 6.6 2.9-1.3-3-6.5H18z" fill="#13201a" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>');
    const ring = make("promo-ring");
    const caption = make("promo-caption");
    const card = make("promo-card");
    const shown = (node) => { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(node).visibility !== "hidden"; };
    window.__promo = {
      cursorTo(x, y) { cursor.style.transform = "translate(" + x + "px, " + y + "px)"; },
      hideCursor() { cursor.style.display = "none"; },
      ring(x, y) { ring.style.left = x + "px"; ring.style.top = y + "px"; ring.classList.remove("go"); void ring.offsetWidth; ring.classList.add("go"); },
      caption(text, where) {
        if (!text) { caption.classList.remove("on"); return; }
        caption.classList.toggle("lift", where === "lift");
        caption.classList.toggle("beside", where === "side");
        caption.textContent = text;
        caption.classList.add("on");
      },
      card(html, look) { if (html) { card.innerHTML = html; card.className = look || ""; } else card.classList.add("off"); },
      playBadge() { make("promo-play"); },
      // The visible button whose label is, or contains, this text.
      button(text, exact, scope) {
        return [...document.querySelectorAll((scope || "main") + " button")].find((b) => shown(b) && (exact ? b.textContent.trim() === text : b.textContent.includes(text)));
      },
      // Where to point at an element, bringing it into view first if need be.
      async point(node) {
        if (!node) return null;
        let r = node.getBoundingClientRect();
        if (!node.closest("header, #player") && (r.top < 120 || r.bottom > innerHeight - 110)) {
          window.scrollBy({ top: r.top - innerHeight * 0.42, behavior: "smooth" });
          await new Promise((done) => setTimeout(done, 700));
          r = node.getBoundingClientRect();
        }
        return { x: Math.round(r.left + Math.min(r.width / 2, 260)), y: Math.round(r.top + r.height / 2) };
      },
    };
    __promo.card(${JSON.stringify("__FIRST_CARD__")});
  };
  if (document.body) build(); else document.addEventListener("DOMContentLoaded", build);
})();`;

const lockup = `<div class="lockup">${logo}</div>`;
const firstCard = `<div>${lockup}<h1>Your Limitless Pendant, still working after December 1, 2026</h1>
  <p>An open-source replacement for the Limitless app. It runs on your own computer.</p>
  <small>The conversations in this video are made up.</small></div>`;
const lastCard = `<div>${lockup}<h1>Keep the pendant. Keep your recordings.</h1>
  <p>Free and open source, under the MIT licence.</p><p class="where">github.com/andreibondarev/limitful</p>
  <small>Limits apply. Not affiliated with Limitless or Meta.</small></div>`;

// The launch cut's cards: one line each, big.
// The first one names Limitless with its own mark and shows the pendant, so nobody has to work out what this is about.
const inline = (file, type) => `data:${type};base64,${readFileSync(join(here, file)).toString("base64")}`;
const hook1 = `<div class="hook"><h1><span class="theirs"><img src="${inline("limitless-mark.svg", "image/svg+xml")}" alt="">Limitless</span><br>shuts down on<br>December 1.</h1>
  <img class="promo-pendant" src="${inline("limitless-pendant.webp", "image/webp")}" alt="The Limitless Pendant"></div>`;
const hook2 = `<div><h1 class="gold">Your pendant doesn’t have to.</h1></div>`;
// What this is, said once before the app appears.
// The name comes up first, on its own; the rest of the card follows two beats later.
const introCard = `<div><p class="intro">Introducing</p>${lockup}
  <h1 class="late">The transcription and intelligence platform for your Limitless pendant.</h1>
  <p class="late">On your own computer, or the cloud you choose. Free and open source.</p></div>`;
const mineCard = `<div><h1>It runs on your computer.</h1><p>No account. No subscription. Nothing leaves it unless you say so.</p></div>`;
const launchLast = `<div>${lockup}<h1>Keep the pendant. Keep your recordings.</h1>
  <p>Free and open source.</p><p class="where">github.com/andreibondarev/limitful</p>
  <small>The conversations in this video are made up. Not affiliated with Limitless or Meta.</small></div>`;

// --- directing: captions, pointing, clicking, typing --------------------------------
const promo = (call) => run(`window.__promo.${call}`);
const caption = (text, where = "") => promo(`caption(${JSON.stringify(text)}, ${JSON.stringify(where)})`);
const card = (html, look = "") => promo(`card(${JSON.stringify(html)}, ${JSON.stringify(look)})`);
const button = (text, { exact = false, scope = "main" } = {}) => `__promo.button(${JSON.stringify(text)}, ${exact}, ${JSON.stringify(scope)})`;
const moveTo = async (element) => {
  await until(element);
  const at = await run(`__promo.point(${element})`);
  await promo(`cursorTo(${at.x}, ${at.y})`);
  await sleep(470);
  await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: at.x, y: at.y });
  return at;
};
const click = async (element, pause = 250) => {
  const at = await moveTo(element);
  await sleep(110);
  await promo(`ring(${at.x}, ${at.y})`);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: at.x, y: at.y, button: "left", clickCount: 1 });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: at.x, y: at.y, button: "left", clickCount: 1 });
  await sleep(pause);
};
const type = async (text, each = 42) => {
  for (const letter of text) {
    await send("Input.insertText", { text: letter });
    // Headless Chrome changes the value without telling the page; say so, as a keyboard would.
    await run("document.activeElement.dispatchEvent(new Event('input', { bubbles: true })); true");
    await sleep(each);
  }
};
const press = async (key, code, keyCode) => {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode: keyCode });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode: keyCode });
};
const scene = (name) => console.log(`${((Date.now() - began) / 1000).toFixed(1).padStart(6)}s  ${name}`);

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: WIDTH, height: HEIGHT, deviceScaleFactor: SCALE, mobile: false });
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: "light" }] });
await send("Page.addScriptToEvaluateOnNewDocument", { source: overlay.replace("__SHORT__", String(SHORT)).replace(JSON.stringify("__FIRST_CARD__"), JSON.stringify(SHORT ? hook1 : firstCard)) });
const yesterday = new Date(Date.now() - 86400000);
const dayKey = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, "0")}-${String(yesterday.getDate()).padStart(2, "0")}`;
await send("Page.navigate", { url: `http://127.0.0.1:${port}/${SHORT ? "#" + dayKey : ""}` });
await until(SHORT ? "window.__promo && document.querySelector('.recap .headline')" : "window.__promo && document.querySelector('.welcome .way')");
await document_fonts();
async function document_fonts() { await run("document.fonts.ready.then(() => true)"); }

const OUT_W = Math.round(WIDTH * SCALE), OUT_H = Math.round(HEIGHT * SCALE);
await send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: OUT_W, maxHeight: OUT_H, everyNthFrame: 1 });
const began = Date.now();

// A caption belongs to the view it describes: it is taken down before the click that
// leaves that view, and the next one goes up once the new view is showing.
if (!SHORT) {
scene("title card");
await sleep(3800);

scene("setup guide");
await caption("The first time you open it, a setup guide gets you going", "side");
await card(null);
await sleep(2300);
await click(button("Connect my pendant"));
await caption("It says what to do before pairing, so no recording is lost", "side");
await sleep(2300);
await click(button("I've done these"));
await caption("It finds your pendant over Bluetooth…", "side");
await until(button("Pair it", { exact: true }));
await sleep(700);
await click(button("Pair it", { exact: true }));
await caption("Pair by cable and keep what is on it, or with its button", "side");
await sleep(2400);
await click(button("Reset the pendant"));
await caption("…one press-and-hold, and it is paired", "side");
await sleep(900);
await click(button("Start pairing"));
await until(button("Continue", { exact: true }));
await sleep(900);
await click(button("Continue", { exact: true }));
await caption("The first sync brings the audio in and turns it into text on your computer", "side");
await sleep(700);
await click(button("Sync now"));
await until(button("Continue", { exact: true }), 30000);
await sleep(1100);
await click(button("Continue", { exact: true }));
await caption("Summaries are optional, and stay off until you choose", "side");
await sleep(2000);
await click(button("Skip", { exact: true }));
await caption("After that it can start at login and keep syncing by itself", "side");
await sleep(2100);
await caption(null);
await click(button("Open your Lifelog"));

scene("a day in the Lifelog");
await until("document.querySelector('details.card')");
await sleep(400);
await click("document.getElementById('prev')");
await until("document.querySelector('.recap .headline')");
await caption("Your Lifelog: every day opens with a recap");
await sleep(2900);
const talk = "[...document.querySelectorAll('details.card summary')].find((s) => s.textContent.includes('Coffee with Elena'))";
await click(`${talk}.querySelector('h2')`);
await caption("Each conversation gets a title, a summary and its full transcript");
await run(`window.scrollBy({ top: ${talk}.getBoundingClientRect().top - 190, behavior: "smooth" })`);
await sleep(3000);

scene("search");
await caption(null);
await run("window.scrollTo({ top: 0, behavior: 'smooth' })");
await click("document.getElementById('search')");
await caption("Search everything that was said");
await type("pilot proposal", 65);
await until("document.getElementById('title').textContent === 'Search' && document.querySelectorAll('main .hit, main .line').length > 0");
await sleep(2300);
await caption(null);
await press("Escape", "Escape", 27);
await sleep(350);

scene("reminders");
await click("document.getElementById('remind')");
await until("document.querySelector('.idea')");
await caption("Reminders are picked out of what people said they would do");
await sleep(1700);
await click("document.querySelector('.idea .round.yes')", 1500);

scene("settings");
await caption(null);
await click("document.getElementById('settings')");
await until("document.querySelector('.sections')");
await caption("Check, sync and control the pendant from the app");
await click(button("Check pendant"));
await until("[...document.querySelectorAll('.reading b')].some((b) => b.textContent === 'nothing')");
await sleep(1500);
await caption(null);
await click("document.querySelector('.sections button[data-pane=transcription]')");
await caption("Private by default: audio stays on your computer unless you choose otherwise");
await sleep(2800);

scene("ask");
// Ask needs Claude chosen. This is the scratch settings file; the answer comes from pretend_server.py.
writeFileSync(join(work, "config.json"), JSON.stringify({ provider: "claude" }));
await caption(null);
await click("document.getElementById('ask')");
await until("document.querySelector('.composer textarea')");
await caption("Ask about anything you've said or heard");
await click("document.querySelector('.composer textarea')");
await type("What does Elena need before a pilot, and when does she decide?", 34);
await sleep(250);
await click("document.querySelector('.composer button[type=submit]')");
await until("document.querySelectorAll('.answer a.cite').length >= 4 && document.querySelector('.working')?.hidden !== false", 30000);
await caption("Answers link to the lines they are based on");
await sleep(2300);
await caption(null);
await click("document.querySelector('.answer a.cite')");
await until("!document.getElementById('player').hidden && document.querySelector('.say.found, .say.on, .line.found, .line.on')");
await caption("…and every link plays the moment it was said", "lift");
await sleep(3300);
if (await run("audio.paused")) console.warn("warning: playback had stopped by the end of the last scene; record again");

scene("closing card");
await caption(null);
await card(lastCard);
await sleep(4600);
} else {
scene("hook");
// The opening cards change on the music's beat: four beats, four, then two and six.
await sleep(4 * BEAT);
await card(hook2);
await sleep(4 * BEAT);
await card(introCard, "closing");
await sleep(2 * BEAT);
await run("document.getElementById('promo-card').classList.add('more'); true");
await sleep(5 * BEAT);
// Behind the card, turn to Settings, so the pendant is the first thing seen of the app.
await run("location.hash = 'settings'; true");
await until("document.querySelector('.sections')");
await sleep(BEAT);

scene("the pendant");
await card(null);
await caption("Your pendant, synced over Bluetooth");
await click(button("Check pendant"));
await until("[...document.querySelectorAll('.reading b')].some((b) => b.textContent === 'nothing')");
await sleep(1900);

scene("a day");
await caption(null);
await run(`location.hash = ${JSON.stringify(dayKey)}; true`);
await until("document.querySelector('.recap .headline')");
await caption("Every day, recapped");
await sleep(2700);
const talk = "[...document.querySelectorAll('details.card summary')].find((s) => s.textContent.includes('Coffee with Elena'))";
await click(`${talk}.querySelector('h2')`);
await caption("Every conversation, transcribed on your computer");
await run(`window.scrollBy({ top: ${talk}.getBoundingClientRect().top - 190, behavior: "smooth" })`);
await sleep(2900);

scene("search");
await caption(null);
await run("window.scrollTo({ top: 0, behavior: 'smooth' })");
await click("document.getElementById('search')");
await caption("Search everything that was said");
await type("pilot proposal", 48);
await until("document.getElementById('title').textContent === 'Search' && document.querySelectorAll('main .hit, main .line').length > 0");
await sleep(1700);
await caption(null);
await press("Escape", "Escape", 27);
await sleep(250);

scene("ask");
await click("document.getElementById('ask')");
await until("document.querySelector('.composer textarea')");
await caption("Ask it anything");
await click("document.querySelector('.composer textarea')");
await type("What does Elena need before a pilot, and when does she decide?", 24);
await sleep(200);
await click("document.querySelector('.composer button[type=submit]')");
await until("document.querySelectorAll('.answer a.cite').length >= 4 && document.querySelector('.working')?.hidden !== false", 30000);
await caption("Every answer points to the moment it was said");
await sleep(2600);

scene("reminders");
await caption(null);
await click("document.getElementById('remind')");
await until("document.querySelector('.idea')");
await caption("It catches what you said you’d do");
await sleep(2600);

scene("cards");
await caption(null);
await card(mineCard);
await sleep(2900);
await card(launchLast, "closing");
await sleep(4000);
}
await send("Page.stopScreencast");
const length = (Date.now() - began) / 1000;
await sleep(400);

// --- the poster: the recap page with a play mark over it ----------------------------
if (!SHORT) {
await run("audio.pause(); document.getElementById('player').hidden = true; __promo.hideCursor(); window.scrollTo(0, 0); true");
await card(null);
await sleep(700);
await run("__promo.playBadge(); true");
await sleep(200);
const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 88 });
writeFileSync(join(here, "poster.jpg"), Buffer.from(shot.result.data, "base64"));
}
ws.close();
stop();

// --- assemble: each frame is held until the next one arrived ------------------------
// Played a little faster than it was filmed: the app's own waits (polling, page loads) drag on film.
const speed = SPEED;
const list = [];
let total = 0;
frames.forEach((frame, n) => {
  const next = frames[n + 1];
  const hold = (next ? Math.max(0.001, next.at - frame.at) : Math.max(0.1, length - (frame.at - frames[0].at))) / speed;
  total += hold;
  list.push(`file '${frame.file}'`, `duration ${hold.toFixed(4)}`);
});
list.push(`file '${frames[frames.length - 1].file}'`);
writeFileSync(join(work, "frames.txt"), list.join("\n") + "\n");
const out = join(here, SHORT ? "limitful-launch.mp4" : "limitful-promo.mp4");
// Music under both: the start of a CC0 track, levelled, fading out under the last card.
const music = process.env.PROMO_SILENT ? null : join(here, "launch-music.ogg");
const sound = music
  ? ["-af", `loudnorm=I=-18:TP=-2:LRA=11,afade=t=in:d=0.25,afade=t=out:st=${Math.max(0, total - 2.2).toFixed(2)}:d=2.2`, "-c:a", "aac", "-b:a", "160k"]
  : ["-an"];
const made = spawnSync("ffmpeg", ["-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", join(work, "frames.txt"), ...(music ? ["-i", music] : []),
  // JPEG frames are full-range; players expect video range, so convert rather than relabel.
  "-vf", `fps=30,scale=${OUT_W}:${OUT_H}:flags=lanczos:in_range=full:out_range=tv,format=yuv420p`,
  "-c:v", "libx264", "-preset", "slow", "-crf", process.env.PROMO_CRF || "25", "-color_range", "tv", "-movflags", "+faststart", ...sound,
  "-t", total.toFixed(3),  // the list has to name the last frame twice, which would otherwise hold it twice as long
  out], { stdio: "inherit" });
if (made.status !== 0) throw new Error("ffmpeg failed");
console.log(`${frames.length} frames, filmed in ${length.toFixed(1)} s, played in ${(length / speed).toFixed(1)} s -> ${out}`);
process.exit(0);
