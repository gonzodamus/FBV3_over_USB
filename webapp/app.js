'use strict';

/* ----------------------------------------------------------------------------
 * FBV Chroma LED Editor: pure Web MIDI sender.
 *
 * Protocol (see the project README):
 *   - Output port whose name contains "FBV 3". Channel 1.
 *   - Control Change. Raw bytes: [0xB0, ledIndex, value]
 *   - CC number = LED index
 *   - CC value  = state * 8 + color   (off => value 0)
 * -------------------------------------------------------------------------- */

const PORT_MATCH = 'FBV 3';
const CC_STATUS = 0xB0; // Control Change, channel 1
const SCENES_KEY = 'fbv3.scenes';
const LAST_KEY = 'fbv3.lastLayout';
const INVERT_KEY = 'fbv3.invert';

// Global LED-mode toggle. CC 16: value 0 = inverted (firmware default; LED lit at
// rest, dark while the switch is pressed), value 1 = stock (LED off at rest, lit
// only while pressed). `invert === true` maps to value 0.
const INVERT_CC = 16;
let invert = true;

// Firmware version query: Line 6 SysEx the pedal answers with an ASCII
// "L6Version:A.B.C.D.E" string. Patched = 1.1.0.0.0 (FBV Chroma 1.1),
// stock = 1.0.2.0.0. Used to decide whether to surface the firmware builder.
const VERSION_QUERY = [0xf0, 0x00, 0x01, 0x0c, 0x11, 0x03, 0x07, 0x00, 0xf7];
const PATCHED_VERSION = '1.1.0.0.0';
let inputPort = null;
// Version detection is retried: on a warm reload the MIDI port can be ready
// before the pedal is, so a single query may get no reply. We resend a few
// times until a version arrives, then stop.
let versionPoll = null;
let versionTries = 0;
let firmwareDetected = false;
const VERSION_MAX_TRIES = 10;
const VERSION_RETRY_MS = 700;

const STATE_OFF = 0;
const STATE_STEADY = 1;
const STATE_BLINK = 2;

// Editor state options. STATE_OFF is still used internally (default, "Off"
// button, presets) but is not offered as a per-LED choice here.
const STATES = [
  { id: STATE_STEADY, label: 'Steady' },
  { id: STATE_BLINK, label: 'Blink' },
];

// color id = low 3 bits of the CC value. `css` is for the on-screen lamp/swatch.
const COLORS = [
  { id: 0, name: 'Red', css: '#ff453a' },
  { id: 1, name: 'Green', css: '#30d158' },
  { id: 2, name: 'Blue', css: '#0a84ff' },
  { id: 3, name: 'Cyan', css: '#2dd4d4' },
  { id: 4, name: 'Yellow', css: '#ffd60a' },
  { id: 5, name: 'Pink', css: '#ff2d95' },
  { id: 6, name: 'Orange', css: '#ff9f0a' },
  { id: 7, name: 'White', css: '#f2f2f7' },
];

// LEDs to control; index === CC number (not contiguous). On-screen placement
// is driven by PAD_ROWS below.
const LEDS = [
  { idx: 0, name: 'FS1' },
  { idx: 1, name: 'FS2' },
  { idx: 2, name: 'FS3' },
  { idx: 3, name: 'FS4' },
  { idx: 4, name: 'FS5' },
  { idx: 5, name: 'A' },
  { idx: 6, name: 'B' },
  { idx: 7, name: 'C' },
  { idx: 8, name: 'D' },
  { idx: 12, name: 'FUNC' },
];

const LED_BY_IDX = {};
LEDS.forEach((led) => {
  LED_BY_IDX[led.idx] = led;
});

// Pedalboard layout: one array per row, holding LED indices. `'blank'` leaves an
// empty slot. Top row is FS1-FS5, a gap, then FUNC in the 7th slot.
const PAD_ROWS = [
  [0, 1, 2, 3, 4, 'blank', 12],
  [5, 6, 7, 8],
];

// Authoritative model: the firmware holds whatever we last sent, so what is
// on screen is what is on the pedal. Keyed by LED index (=== CC number);
// indices are not contiguous, so this is an object rather than an array.
const model = {};
LEDS.forEach((led) => {
  model[led.idx] = { state: STATE_OFF, color: 1 /* green */ };
});

let midiAccess = null;
let outputPort = null;

// DOM refs filled in on load.
const dom = {};

/* ---------- Protocol helpers ---------- */

function ccValue(led) {
  return led.state === STATE_OFF ? 0 : led.state * 8 + led.color;
}

function sendLed(idx) {
  const value = ccValue(model[idx]);
  if (outputPort) {
    try {
      outputPort.send([CC_STATUS, idx, value]);
    } catch (err) {
      console.error(`MIDI send failed for LED ${idx}`, err);
    }
  }
  return value;
}

function sendAll() {
  LEDS.forEach((led) => sendLed(led.idx));
}

function sendInvert() {
  if (outputPort) {
    try {
      outputPort.send([CC_STATUS, INVERT_CC, invert ? 0 : 1]);
    } catch (err) {
      console.error('MIDI send failed for invert flag', err);
    }
  }
}

/* ---------- MIDI setup ---------- */

async function initMidi() {
  if (!navigator.requestMIDIAccess) {
    setStatus('error', 'Web MIDI not supported');
    showBanner(
      '<strong>This browser has no Web MIDI.</strong> Open this page in ' +
        '<strong>Chrome</strong> or <strong>Edge</strong> (desktop). Safari and Firefox ' +
        'do not support the Web MIDI API.'
    );
    return;
  }

  try {
    // sysex:true lets us query the pedal's firmware version (a SysEx message).
    midiAccess = await navigator.requestMIDIAccess({ sysex: true });
  } catch (err) {
    setStatus('error', 'MIDI access denied');
    showBanner(
      '<strong>Could not get MIDI access.</strong> Allow the MIDI permission and reload. ' +
        'Web MIDI also requires a secure context: serve this over <code>https</code> or ' +
        '<code>http://localhost</code>, not <code>file://</code>. ' +
        `<br>Details: ${escapeHtml(String(err && err.message ? err.message : err))}`
    );
    return;
  }

  midiAccess.onstatechange = () => { findPort(); };
  findPort();
}

async function findPort() {
  const prevId = outputPort ? outputPort.id : null;
  let out = null;
  for (const p of midiAccess.outputs.values()) {
    if (p.name && p.name.includes(PORT_MATCH)) { out = p; break; }
  }
  let inp = null;
  for (const p of midiAccess.inputs.values()) {
    if (p.name && p.name.includes(PORT_MATCH)) { inp = p; break; }
  }

  outputPort = out;

  // Listen on the matching input port. On a warm reload the input port can show
  // up a moment AFTER the output (or after this first scan), so binding it is
  // tracked separately from the output connection.
  const inputIsNew = inp && inp !== inputPort;
  if (inputIsNew) {
    inputPort = inp;
    inputPort.onmidimessage = onMidiMessage;
  } else if (!inp) {
    inputPort = null;
  }

  if (out) {
    setStatus('ok', `Connected: ${out.name}`);
    hideBanner();
    const outputIsNew = out.id !== prevId;
    if (outputIsNew) firmwareDetected = false; // a (re)connected pedal might differ
    console.debug(`[FBV] findPort: out=${!!out} in=${!!inp} outNew=${outputIsNew} inNew=${inputIsNew} detected=${firmwareDetected}`);

    // Ports must be open() before they pass traffic, and open() is async. Query
    // the version whenever we have both ports but no detection yet, regardless of
    // WHICH port just appeared. This covers refresh, where the input port often
    // arrives after the output and a one-shot "on new output" query would miss it.
    if (inp && !firmwareDetected && (outputIsNew || inputIsNew)) {
      // On a warm reload the browser returns ports that report "open" but whose
      // data path is stale (a no-op open() won't revive it). Force a close()/open()
      // cycle to rebuild the connection, which is what a physical replug does.
      try {
        await Promise.all([out.close(), inp.close()]);
        await Promise.all([out.open(), inp.open()]);
        console.debug(`[FBV] ports reopened: out=${out.connection}/${out.state} in=${inp.connection}/${inp.state}`);
      } catch (err) {
        console.error('MIDI port reopen failed', err);
      }
      if (outputIsNew) {
        sendInvert();
        sendAll();
      }
      queryVersion();
    }
  } else {
    setStatus('pending', 'Pedal not found');
    showBanner(
      `<strong>No “${PORT_MATCH}” MIDI output found.</strong> Connect the FBV3 by USB ` +
        '(it must be running the patched firmware, <code>FBV Chroma 1.1</code>). ' +
        'It will be detected automatically when it appears, no reload needed.'
    );
    stopVersionPoll();
    firmwareDetected = false;
    setFirmwareState('unknown');
  }
}

// Start (or restart) version detection: send the query now and keep retrying
// until a reply sets the firmware state or we run out of tries. Retrying is what
// makes detection survive a warm reload, where the port is ready before the pedal.
function queryVersion() {
  stopVersionPoll();
  versionTries = 0;
  const attempt = () => {
    if (!outputPort) return stopVersionPoll();
    versionTries++;
    try {
      outputPort.send(VERSION_QUERY);
      console.debug(`[FBV] version query sent (try ${versionTries})`);
    } catch (err) {
      console.error('version query failed', err);
    }
    if (versionTries >= VERSION_MAX_TRIES) {
      stopVersionPoll();
      console.debug('[FBV] version query gave up after max tries (no reply received)');
    }
  };
  attempt();
  versionPoll = setInterval(attempt, VERSION_RETRY_MS);
}

function stopVersionPoll() {
  if (versionPoll) {
    clearInterval(versionPoll);
    versionPoll = null;
  }
}

// Parse the pedal's SysEx reply for "L6Version:A.B.C.D.E". A long SysEx reply may
// arrive split across several onmidimessage events, so accumulate bytes from F0
// (start) to F7 (end) and scan the assembled buffer.
let sysexBuf = [];
function onMidiMessage(e) {
  console.debug('[FBV] MIDI in:', Array.from(e.data, (b) => b.toString(16).padStart(2, '0')).join(' '));
  for (const b of e.data) {
    if (b === 0xf0) sysexBuf = [];
    sysexBuf.push(b);
    if (b === 0xf7) {
      const text = String.fromCharCode.apply(null, sysexBuf);
      sysexBuf = [];
      const m = text.match(/L6Version:([0-9.]+)/);
      if (m) {
        stopVersionPoll();
        firmwareDetected = true;
        console.debug(`[FBV] version reply: ${m[1]} (${m[1] === PATCHED_VERSION ? 'patched' : 'stock'})`);
        setFirmwareState(m[1] === PATCHED_VERSION ? 'patched' : 'stock', m[1]);
      }
    }
  }
  // Cap the buffer so a never-terminated stream can't grow unbounded.
  if (sysexBuf.length > 4096) sysexBuf = [];
}

/* ---------- Status / banner ---------- */

function setStatus(kind, text) {
  dom.status.className = `status status--${kind}`;
  dom.status.querySelector('.status__text').textContent = text;
}

function showBanner(html) {
  dom.banner.innerHTML = html;
  dom.banner.hidden = false;
}

function hideBanner() {
  dom.banner.hidden = true;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
}

/* ---------- Rendering ---------- */

// The LED currently being edited (its index, === CC number).
let selectedIdx = LEDS[0].idx;

function buildBoard() {
  dom.board.innerHTML = '';
  dom.board.appendChild(buildPedalboard());
  dom.board.appendChild(buildEditor());
}

function buildPedalboard() {
  const board = document.createElement('div');
  board.className = 'pedalboard';

  // Flattened into the 7-column grid. The first row fills all 7 columns (incl.
  // the blank), so the second row (A-D) wraps cleanly underneath.
  for (const row of PAD_ROWS) {
    for (const item of row) {
      if (item === 'blank') {
        const blank = document.createElement('span');
        blank.className = 'pad-blank';
        board.appendChild(blank);
        continue;
      }
      board.appendChild(buildPad(LED_BY_IDX[item]));
    }
  }
  return board;
}

function buildPad(led) {
  const pad = document.createElement('button');
  pad.className = 'pad';
  pad.dataset.idx = led.idx;
  pad.title = `${led.name} (CC ${led.idx})`;
  pad.addEventListener('click', () => select(led.idx));

  const lamp = document.createElement('span');
  lamp.className = 'lamp pad__lamp';
  pad.appendChild(lamp);

  const label = document.createElement('span');
  label.className = 'pad__label';
  label.textContent = led.name;
  pad.appendChild(label);

  return pad;
}

// The single shared editor: swatches + state, applied to the selected LED.
function buildEditor() {
  const editor = document.createElement('div');
  editor.className = 'editor';

  const head = document.createElement('div');
  head.className = 'editor__head';
  head.innerHTML =
    '<span class="editor__title">Editing</span>' +
    '<span id="editName" class="editor__name"></span>' +
    '<span id="editCC" class="editor__cc"></span>';
  editor.appendChild(head);

  const row = document.createElement('div');
  row.className = 'editor__row';

  const swatches = document.createElement('div');
  swatches.className = 'swatches editor__swatches';
  for (const color of COLORS) {
    const sw = document.createElement('button');
    sw.className = 'swatch';
    sw.style.background = color.css;
    sw.dataset.color = color.id;
    sw.title = color.name;
    sw.setAttribute('aria-label', color.name);
    sw.addEventListener('click', () => onColorPick(selectedIdx, color.id));
    swatches.appendChild(sw);
  }
  row.appendChild(swatches);

  const states = document.createElement('div');
  states.className = 'states editor__states';
  for (const st of STATES) {
    const btn = document.createElement('button');
    btn.className = 'state-btn';
    btn.dataset.state = st.id;
    btn.textContent = st.label;
    btn.addEventListener('click', () => onStatePick(selectedIdx, st.id));
    states.appendChild(btn);
  }
  row.appendChild(states);

  editor.appendChild(row);
  return editor;
}

function refreshPad(idx) {
  const lamp = dom.board.querySelector(`.pad[data-idx="${idx}"] .pad__lamp`);
  if (!lamp) return;
  const m = model[idx];
  lamp.classList.toggle('lamp--on', m.state !== STATE_OFF);
  lamp.classList.toggle('lamp--blink', m.state === STATE_BLINK);
  lamp.style.setProperty('--glow', m.state === STATE_OFF ? 'transparent' : COLORS[m.color].css);
}

function refreshEditor() {
  const led = LED_BY_IDX[selectedIdx];
  const m = model[selectedIdx];

  dom.board.querySelectorAll('.pad').forEach((pad) => {
    pad.classList.toggle('pad--selected', Number(pad.dataset.idx) === selectedIdx);
  });

  document.getElementById('editName').textContent = led.name;
  document.getElementById('editCC').textContent = `CC ${selectedIdx}`;

  dom.board.querySelectorAll('.editor__swatches .swatch').forEach((sw) => {
    sw.classList.toggle('swatch--active', Number(sw.dataset.color) === m.color);
  });
  dom.board.querySelectorAll('.editor__states .state-btn').forEach((btn) => {
    btn.classList.toggle('state-btn--active', Number(btn.dataset.state) === m.state);
  });
}

function refreshAll() {
  LEDS.forEach((led) => refreshPad(led.idx));
  refreshEditor();
}

/* ---------- Interaction ---------- */

function select(idx) {
  selectedIdx = idx;
  refreshEditor();
}

function onColorPick(idx, colorId) {
  const led = model[idx];
  led.color = colorId;
  // Picking a color while off implies "turn it on": promote to steady so the
  // click produces visible feedback.
  if (led.state === STATE_OFF) led.state = STATE_STEADY;
  commit(idx);
}

function onStatePick(idx, stateId) {
  model[idx].state = stateId;
  commit(idx);
}

// Apply one LED: update its lamp + the editor, push to the pedal, and persist.
function commit(idx) {
  refreshPad(idx);
  if (idx === selectedIdx) refreshEditor();
  sendLed(idx);
  saveLast();
}

// Load a saved layout array into the model (no rendering/sending). Tolerates
// older scenes that lack an explicit idx by falling back to position.
function applyLayoutToModel(layout) {
  if (!Array.isArray(layout)) return;
  layout.forEach((s, i) => {
    const idx = s && Number.isInteger(s.idx) ? s.idx : LEDS[i] && LEDS[i].idx;
    if (idx == null || !model[idx]) return;
    model[idx].state = clampState(s.state);
    model[idx].color = clampColor(s.color);
  });
}

function setLayout(layout, { send }) {
  applyLayoutToModel(layout);
  refreshAll();
  saveLast();
  if (send) sendAll();
}

/* ---------- Presets ---------- */

function applyPreset(name) {
  if (name === 'rainbow') {
    // Spread the 8 colors across the LEDs, steady.
    setLayout(
      LEDS.map((led, i) => ({ idx: led.idx, state: STATE_STEADY, color: i % COLORS.length })),
      { send: true }
    );
  } else if (name === 'white') {
    setLayout(LEDS.map((led) => ({ idx: led.idx, state: STATE_STEADY, color: 7 })), {
      send: true,
    });
  }
}

/* ---------- Scenes (localStorage) ---------- */

function getScenes() {
  try {
    const raw = localStorage.getItem(SCENES_KEY);
    const obj = raw ? JSON.parse(raw) : {};
    return obj && typeof obj === 'object' ? obj : {};
  } catch {
    return {};
  }
}

function putScenes(scenes) {
  localStorage.setItem(SCENES_KEY, JSON.stringify(scenes));
}

function snapshot() {
  return LEDS.map((led) => ({
    idx: led.idx,
    state: model[led.idx].state,
    color: model[led.idx].color,
  }));
}

// Render one chip per saved scene, inline with the presets. Clicking the name
// applies the scene; the × deletes it.
function renderScenes() {
  const scenes = getScenes();
  const names = Object.keys(scenes).sort((a, b) => a.localeCompare(b));
  const wrap = dom.sceneChips;
  wrap.innerHTML = '';

  for (const name of names) {
    const chip = document.createElement('span');
    chip.className = 'chip';

    const apply = document.createElement('button');
    apply.className = 'btn chip__apply';
    apply.textContent = name;
    apply.title = `Apply scene “${name}”`;
    apply.addEventListener('click', () => applyScene(name));

    const del = document.createElement('button');
    del.className = 'chip__del';
    del.textContent = '×';
    del.title = `Delete scene “${name}”`;
    del.setAttribute('aria-label', `Delete scene ${name}`);
    del.addEventListener('click', () => deleteScene(name));

    chip.appendChild(apply);
    chip.appendChild(del);
    wrap.appendChild(chip);
  }
}

function saveScene() {
  const name = prompt('Save current layout as:', '');
  if (name == null) return;
  const trimmed = name.trim();
  if (!trimmed) return;

  const scenes = getScenes();
  if (scenes[trimmed] && !confirm(`Overwrite scene “${trimmed}”?`)) return;

  scenes[trimmed] = snapshot();
  putScenes(scenes);
  renderScenes();
}

function applyScene(name) {
  const scenes = getScenes();
  const layout = scenes[name];
  if (!Array.isArray(layout)) return;
  setLayout(layout, { send: true });
}

function deleteScene(name) {
  if (!confirm(`Delete scene “${name}”?`)) return;
  const scenes = getScenes();
  delete scenes[name];
  putScenes(scenes);
  renderScenes();
}

/* ---------- Global invert toggle ---------- */

function toggleInvert() {
  invert = !invert;
  refreshInvert();
  sendInvert();
  try {
    localStorage.setItem(INVERT_KEY, JSON.stringify(invert));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

function loadInvert() {
  try {
    const raw = localStorage.getItem(INVERT_KEY);
    if (raw != null) invert = JSON.parse(raw) !== false;
  } catch {
    /* ignore malformed data */
  }
}

function refreshInvert() {
  const btn = dom.invertToggle;
  btn.setAttribute('aria-pressed', String(invert));
  btn.textContent = `Invert: ${invert ? 'On' : 'Off'}`;
  btn.title = invert
    ? 'Inverted (default): LED lit at rest, dark while pressed. Click for stock mode.'
    : 'Stock: LED off at rest, lit only while pressed. Click to restore inverted (default).';
}

/* ---------- Last-layout persistence (survive reload) ---------- */

function saveLast() {
  try {
    localStorage.setItem(LAST_KEY, JSON.stringify(snapshot()));
  } catch {
    /* ignore quota / private-mode errors */
  }
}

function loadLast() {
  try {
    const raw = localStorage.getItem(LAST_KEY);
    if (raw) applyLayoutToModel(JSON.parse(raw));
  } catch {
    /* ignore malformed data */
  }
}

/* ---------- Validation ---------- */

function clampState(v) {
  v = Number(v);
  return v === STATE_STEADY || v === STATE_BLINK ? v : STATE_OFF;
}

function clampColor(v) {
  v = Number(v);
  return Number.isInteger(v) && v >= 0 && v <= 7 ? v : 0;
}

/* ---------- Wire up ---------- */

function init() {
  dom.status = document.getElementById('status');
  dom.banner = document.getElementById('banner');
  dom.board = document.getElementById('board');
  dom.invertToggle = document.getElementById('invertToggle');
  dom.sceneChips = document.getElementById('sceneChips');
  dom.saveScene = document.getElementById('saveScene');

  loadLast();
  loadInvert();
  buildBoard();
  refreshAll();
  refreshInvert();
  renderScenes();

  dom.invertToggle.addEventListener('click', toggleInvert);
  dom.saveScene.addEventListener('click', saveScene);

  document.querySelectorAll('[data-preset]').forEach((btn) => {
    btn.addEventListener('click', () => applyPreset(btn.dataset.preset));
  });

  initBuilder();
  initMidi();
}

/* ---------- Firmware builder (in-browser patcher) ---------- */

function initBuilder() {
  const input = document.getElementById('fwFile');
  const msg = document.getElementById('builderMsg');
  if (!input || !msg) return;

  if (!browserCanPatch()) {
    msg.textContent =
      'This browser cannot build firmware (no compression API). Use Chrome or Edge, ' +
      'or run manual/build/build_firmware.py instead.';
    msg.className = 'builder__msg builder__msg--error';
    input.disabled = true;
    return;
  }

  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    msg.textContent = `Building from ${file.name}…`;
    msg.className = 'builder__msg';
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const result = await patchFirmware(bytes);
      downloadBlob(result.blob, result.name);
      msg.textContent = `Done. ${result.name} downloaded. Flash it with the Line 6 FBV3 Updater (update from a file).`;
      msg.className = 'builder__msg builder__msg--ok';
    } catch (err) {
      msg.textContent = err && err.message ? err.message : String(err);
      msg.className = 'builder__msg builder__msg--error';
    } finally {
      input.value = ''; // allow re-picking the same file
    }
  });
}

// Show/hide the firmware builder based on the connected pedal's firmware:
//   'patched' -> collapse and confirm; 'stock' -> open and prompt; 'unknown' -> show.
function setFirmwareState(state, version) {
  const builder = document.getElementById('builder');
  const summary = document.getElementById('builderSummary');
  if (!builder || !summary) return;

  if (state === 'patched') {
    summary.textContent = `✓ FBV Chroma ${version === PATCHED_VERSION ? '1.1' : version} detected. Firmware is up to date.`;
    builder.open = false;
    builder.classList.add('builder--ok');
    builder.classList.remove('builder--attention');
  } else if (state === 'stock') {
    summary.textContent = 'Your pedal has stock firmware. Build the FBV Chroma patch ›';
    builder.open = true;
    builder.classList.add('builder--attention');
    builder.classList.remove('builder--ok');
  } else {
    summary.textContent = 'First time here? Build the patched firmware ›';
    builder.classList.remove('builder--ok', 'builder--attention');
  }
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.addEventListener('DOMContentLoaded', init);
