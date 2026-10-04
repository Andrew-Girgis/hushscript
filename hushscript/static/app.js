"use strict";
const $ = (id) => document.getElementById(id);
const state = {queue: [], results: [], running: false, stopped: false, ready: false,
  active: null, controller: null, downloaded: true};
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const notice = (message) => { $("notice").textContent = message; $("notice").hidden = !message; };
const bytes = (n) => (n / 1048576).toFixed(1) + " MiB";
function sync() {
  $("count").textContent = state.queue.length + " files";
  $("completed").textContent = state.results.length + " ready";
  $("start").disabled = state.running || !state.ready || !state.queue.some((x) => x.file && x.phase === "Waiting");
  $("files").disabled = state.running;
  $("diarize").disabled = state.running;
  $("cancel").hidden = !state.running;
  $("clear").disabled = state.running || (!state.queue.length && !state.results.length);
  $("download").disabled = !state.results.length;
  $("empty").hidden = !!state.results.length;
  $("results").hidden = !state.results.length;
}
function drawQueue() {
  $("queue").replaceChildren();
  for (const item of state.queue) {
    const li = document.createElement("li");
    li.classList.toggle("failed", item.phase === "Failed");
    const name = document.createElement("span"); name.className = "filename";
    name.textContent = item.name; name.title = item.name;
    const phase = document.createElement("span"); phase.className = "phase";
    phase.textContent = item.message || item.phase;
    li.append(name, phase); $("queue").append(li);
  }
  sync();
}
function addFiles(files) {
  if (state.running) return;
  const incoming = Array.from(files);
  if (state.queue.length + incoming.length > 50) {
    notice("Choose at most 50 files per batch. Clear the current batch to start another."); return;
  }
  const tooLarge = incoming.find((f) => f.size > 250 * 1048576);
  if (tooLarge) { notice(tooLarge.name + " is " + bytes(tooLarge.size) + ". The limit is 250 MiB per file."); return; }
  if (incoming.some((f) => f.size === 0)) { notice("One of these files is empty. Remove it and try again."); return; }
  for (const file of incoming) state.queue.push({file, name: file.name, phase: "Waiting"});
  notice(""); drawQueue();
}
$("files").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
for (const type of ["dragenter", "dragover"]) $("drop").addEventListener(type, (e) => {
  e.preventDefault(); if (!state.running) $("drop").classList.add("drag");
});
for (const type of ["dragleave", "drop"]) $("drop").addEventListener(type, (e) => {
  e.preventDefault(); $("drop").classList.remove("drag");
});
$("drop").addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
async function api(path, options = {}) {
  const response = await fetch(path, {cache: "no-store", ...options});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(typeof body.detail === "string" ? body.detail : "The local service could not complete this request.");
    error.status = response.status; throw error;
  }
  return response.status === 204 ? null : response.json();
}
function auth(job) { return {Authorization: "Bearer " + job.token}; }
async function discard(job) {
  if (!job) return;
  await api("/api/jobs/" + job.id, {method: "DELETE", headers: auth(job)})
    .catch((e) => { if (e.status !== 404) throw e; });
}
async function health() {
  try {
    const data = await api("/api/health"); state.ready = data.ready;
    $("health").textContent = data.ready ? "Local worker · " + data.device.toUpperCase() : "Setup required";
    $("health").classList.toggle("ready", data.ready);
    if (!data.ready) notice(data.problems.join(" "));
  } catch { state.ready = false; $("health").textContent = "Worker unavailable"; }
  sync();
}
function showResult() {
  const record = state.results[Number($("result-select").value) || 0];
  if (!record) return;
  $("preview").textContent = record.files["transcript.txt"];
  $("result-meta").textContent = record.result.duration_seconds.toFixed(1) + "s audio · " +
    record.result.processing_seconds.toFixed(1) + "s processing · " +
    (record.result.diarization ? record.result.speakers.length + " speaker labels" : "Speaker labels off");
  $("review-notes").replaceChildren();
  for (const warning of record.result.warnings) {
    const p = document.createElement("p"); p.textContent = warning; $("review-notes").append(p);
  }
}
$("result-select").addEventListener("change", showResult);
function addResult(record, item) {
  record.name = item.name; state.results.push(record); state.downloaded = false;
  const opt = document.createElement("option");
  opt.value = String(state.results.length - 1); opt.textContent = item.name;
  $("result-select").append(opt); $("result-select").value = opt.value; showResult();
}
async function run() {
  state.running = true; state.stopped = false; notice(""); sync();
  const diarize = $("diarize").checked;
  for (const item of state.queue) {
    if (state.stopped) break;
    if (!item.file || item.phase !== "Waiting") continue;
    let job = null;
    const abort = new AbortController(); state.controller = abort;
    try {
      item.phase = "Waiting for worker"; drawQueue();
      while (!job && !state.stopped) {
        try {
          // Do not abort reservation: if it succeeds we need its capability to cancel it.
          job = await api("/api/jobs", {method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({filename: item.name.slice(0, 160), diarize})});
        } catch (e) {
          if (e.status !== 409) throw e;
          await pause(2000);
        }
      }
      if (!job) break;
      state.active = job;
      if (state.stopped) throw new DOMException("Cancelled", "AbortError");
      item.phase = "Uploading"; drawQueue();
      await api("/api/jobs/" + job.id + "/audio", {method: "PUT",
        headers: {...auth(job), "Content-Type": "application/octet-stream"},
        body: item.file, signal: abort.signal});
      item.file = null;
      let status;
      do {
        await pause(1000);
        if (state.stopped) throw new DOMException("Cancelled", "AbortError");
        status = await api("/api/jobs/" + job.id, {headers: auth(job), signal: abort.signal});
        item.phase = "Transcribing";
        item.message = "Transcribing · " + Math.round(status.elapsed_seconds) + "s";
        drawQueue();
      } while (status.status === "processing");
      if (status.status !== "ready") throw new Error(status.error || "Processing was interrupted.");
      const record = await api("/api/jobs/" + job.id + "/result?format=files",
        {headers: auth(job), signal: abort.signal});
      addResult(record, item);
      item.phase = "Ready"; item.message = "Ready · held in this tab";
    } catch (e) {
      item.phase = state.stopped || e.name === "AbortError" ? "Cancelled" : "Failed";
      item.message = item.phase === "Failed" ? e.message : "Cancelled";
    } finally {
      item.file = null;
      await discard(job).catch(() => notice(
        "A server cleanup acknowledgement failed. The server will remove abandoned work automatically and results within 15 minutes."));
      state.active = null; state.controller = null; drawQueue();
    }
  }
  if (state.stopped) for (const item of state.queue) {
    if (item.file) { item.file = null; item.phase = "Cancelled"; item.message = ""; }
  }
  state.running = false; drawQueue();
}
$("start").addEventListener("click", run);
$("cancel").addEventListener("click", () => {
  state.stopped = true; state.controller?.abort();
  discard(state.active).catch(() => {});
});
$("clear").addEventListener("click", () => {
  state.queue = []; state.results = []; state.downloaded = true;
  $("result-select").replaceChildren(); $("preview").textContent = "";
  $("review-notes").replaceChildren(); notice(""); drawQueue();
});
// Small ZIP writer (STORE): no dependency, remote script, temporary server file, or ZIP64.
const crcTable = Uint32Array.from({length: 256}, (_, n) => {
  for (let k = 0; k < 8; k++) n = (n >>> 1) ^ ((n & 1) ? 0xedb88320 : 0);
  return n >>> 0;
});
function crc32(data) {
  let crc = 0xffffffff;
  for (const b of data) crc = (crc >>> 8) ^ crcTable[(crc ^ b) & 255];
  return (crc ^ 0xffffffff) >>> 0;
}
function makeZip(files) {
  const encoder = new TextEncoder(), parts = [], directory = [];
  let offset = 0, directorySize = 0;
  for (const [path, content] of files) {
    const name = encoder.encode(path), data = encoder.encode(content), crc = crc32(data);
    const local = new Uint8Array(30 + name.length), l = new DataView(local.buffer);
    l.setUint32(0, 0x04034b50, true); l.setUint16(4, 20, true); l.setUint16(6, 0x800, true);
    l.setUint16(12, 33, true); l.setUint32(14, crc, true);
    l.setUint32(18, data.length, true); l.setUint32(22, data.length, true);
    l.setUint16(26, name.length, true); local.set(name, 30);
    const central = new Uint8Array(46 + name.length), c = new DataView(central.buffer);
    c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true);
    c.setUint16(8, 0x800, true); c.setUint16(14, 33, true); c.setUint32(16, crc, true);
    c.setUint32(20, data.length, true); c.setUint32(24, data.length, true);
    c.setUint16(28, name.length, true); c.setUint32(42, offset, true); central.set(name, 46);
    parts.push(local, data); directory.push(central);
    offset += local.length + data.length; directorySize += central.length;
  }
  const end = new Uint8Array(22), view = new DataView(end.buffer);
  view.setUint32(0, 0x06054b50, true); view.setUint16(8, files.length, true);
  view.setUint16(10, files.length, true); view.setUint32(12, directorySize, true);
  view.setUint32(16, offset, true);
  return new Blob([...parts, ...directory, end], {type: "application/zip"});
}
$("download").addEventListener("click", () => {
  const files = [];
  state.results.forEach((record, i) => {
    const folder = String(i + 1).padStart(2, "0") + "-" +
      (record.name.replace(/\.[^.]*$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80) || "recording");
    for (const [name, content] of Object.entries(record.files)) files.push([folder + "/" + name, content]);
  });
  const url = URL.createObjectURL(makeZip(files));
  const anchor = document.createElement("a");
  anchor.href = url; anchor.download = "hushscript-transcripts.zip";
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  state.downloaded = true;
  $("download-note").textContent = "Download requested. Check your Downloads folder before clearing this tab.";
});
window.addEventListener("beforeunload", (e) => {
  if (state.running || (state.results.length && !state.downloaded)) { e.preventDefault(); e.returnValue = ""; }
});
window.addEventListener("pagehide", () => {
  if (state.active) fetch("/api/jobs/" + state.active.id, {
    method: "DELETE", headers: auth(state.active), keepalive: true, cache: "no-store"
  }).catch(() => {});
});
health();
setInterval(health, 10000);
