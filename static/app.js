const { contentTypes, defaultTypes } = window.CONFIG;
const $ = (id) => document.getElementById(id);

const state = {
  platform: null,
  selectedJob: null,
  logLines: [],
  logNext: 0,
  pollTimer: null,
};

function detectPlatform(text) {
  const t = text.toLowerCase();
  if (t.includes("instagram.com") || t.includes("instagr.am")) return "instagram";
  if (t.includes("facebook.com") || t.includes("fb.watch") || t.includes("fb.com")) return "facebook";
  if (t.includes("youtube.com") || t.includes("youtu.be")) return "youtube";
  return null;
}

function updatePlatform() {
  const detected = detectPlatform($("target").value);
  const platform = detected || $("platform").value || null;
  $("detected").textContent = detected ? `— detected ${detected}` : "";
  $("quality-field").classList.toggle("hidden", platform === "instagram");
  $("batch-field").classList.toggle("hidden", platform !== "facebook");
  if (platform === state.platform) return;
  state.platform = platform;

  const box = $("types");
  box.innerHTML = "";
  if (!platform) {
    box.innerHTML = '<em class="muted">Enter a link or choose a platform</em>';
    return;
  }
  for (const type of contentTypes[platform]) {
    const label = document.createElement("label");
    label.className = "chip";
    label.innerHTML = `<input type="checkbox" value="${type}"><span>${type}</span>`;
    label.querySelector("input").checked = defaultTypes[platform].includes(type);
    box.appendChild(label);
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

async function submitForm(event) {
  event.preventDefault();
  $("form-error").textContent = "";
  const types = [...document.querySelectorAll("#types input:checked")].map((i) => i.value);
  const payload = {
    target: $("target").value,
    platform: $("platform").value,
    limit: $("limit").value,
    batch_size: $("batch_size").value,
    quality: $("quality").value,
    types,
    browser: $("browser").value,
    cookies_file: $("cookies_file").value,
    metadata: $("metadata").checked,
  };
  if (state.platform && types.length === 0) {
    $("form-error").textContent = "Pick at least one thing to download.";
    return;
  }
  $("submit").disabled = true;
  try {
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    selectJob(job.id);
    refreshJobs();
  } catch (err) {
    $("form-error").textContent = err.message;
  } finally {
    $("submit").disabled = false;
  }
}

const STATUS_LABEL = {
  queued: "Queued",
  running: "Running",
  done: "Done",
  finished_with_errors: "Finished with errors",
  cancelled: "Cancelled",
};

async function refreshJobs() {
  const jobs = await api("/api/jobs");
  const box = $("jobs");
  if (!jobs.length) return;
  box.innerHTML = "";
  for (const job of jobs) {
    const row = document.createElement("div");
    row.className = "job" + (job.id === state.selectedJob ? " selected" : "");
    row.innerHTML = `
      <span class="status ${job.status}">${STATUS_LABEL[job.status] || job.status}</span>
      <span class="job-label"></span>
      ${["queued", "running"].includes(job.status) ? '<button class="secondary small">Cancel</button>' : ""}`;
    row.querySelector(".job-label").textContent = job.label;
    row.addEventListener("click", () => selectJob(job.id));
    const cancel = row.querySelector("button");
    if (cancel) {
      cancel.addEventListener("click", async (e) => {
        e.stopPropagation();
        await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
        refreshJobs();
      });
    }
    box.appendChild(row);
  }
}

function selectJob(id) {
  state.selectedJob = id;
  state.logLines = [];
  state.logNext = 0;
  $("log").classList.remove("hidden");
  $("log").textContent = "";
  clearTimeout(state.pollTimer);
  pollLog();
  refreshJobs();
}

async function pollLog() {
  const id = state.selectedJob;
  if (!id) return;
  try {
    // Re-request the last line: yt-dlp progress lines are updated in place.
    const since = Math.max(state.logNext - 1, 0);
    const data = await api(`/api/jobs/${id}?since=${since}`);
    if (id !== state.selectedJob) return;
    const base = state.logNext - state.logLines.length;
    state.logLines.splice(Math.max(data.from - base, 0), Infinity, ...data.lines);
    state.logNext = data.next;

    const log = $("log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.textContent = state.logLines.join("\n");
    if (atBottom) log.scrollTop = log.scrollHeight;

    if (["queued", "running"].includes(data.status)) {
      state.pollTimer = setTimeout(pollLog, 1000);
    } else {
      refreshJobs();
      refreshFiles();
    }
  } catch {
    state.pollTimer = setTimeout(pollLog, 3000);
  }
}

function formatSize(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return `${bytes.toFixed(i ? 1 : 0)} ${units[i]}`;
}

async function refreshFiles() {
  const files = await api("/api/files");
  const box = $("files");
  if (!files.length) {
    box.innerHTML = '<em class="muted">Nothing downloaded yet.</em>';
    return;
  }
  box.innerHTML = "";
  for (const file of files) {
    const url = "/files/" + file.path.split("/").map(encodeURIComponent).join("/");
    const tile = document.createElement("a");
    tile.className = "tile";
    tile.href = url;
    tile.target = "_blank";
    let preview;
    if (file.kind === "image") preview = `<img loading="lazy" src="${url}">`;
    else if (file.kind === "video") preview = `<video preload="metadata" muted src="${url}#t=0.5"></video><span class="badge">▶</span>`;
    else preview = `<div class="placeholder">${file.kind === "audio" ? "♫" : "📄"}</div>`;
    tile.innerHTML = `<div class="thumb">${preview}</div><div class="meta"><span class="name"></span><small></small></div>`;
    tile.querySelector(".name").textContent = file.path;
    tile.querySelector("small").textContent = formatSize(file.size);
    box.appendChild(tile);
  }
}

let authTimer = null;

async function refreshAccounts() {
  clearTimeout(authTimer);
  let sites;
  try {
    sites = await api("/api/auth");
  } catch {
    authTimer = setTimeout(refreshAccounts, 5000);
    return;
  }
  const box = $("accounts");
  box.innerHTML = "";
  let busy = false;
  for (const s of Object.values(sites)) {
    const inProgress = ["starting", "waiting"].includes(s.flow);
    busy ||= inProgress;
    const row = document.createElement("div");
    row.className = "account";
    const badge = inProgress
      ? '<span class="status running">Waiting for login…</span>'
      : s.logged_in
        ? '<span class="status done">Logged in</span>'
        : '<span class="status">Not logged in</span>';
    row.innerHTML = `
      <strong>${s.name}</strong>${badge}
      <span class="account-msg"></span>
      <span class="account-actions"></span>`;
    let msg = s.message || "";
    if (!msg && s.logged_in && s.saved_at) {
      msg = `Session saved ${new Date(s.saved_at * 1000).toLocaleString()}` + (s.user_id ? ` · user id ${s.user_id}` : "");
    }
    row.querySelector(".account-msg").textContent = msg;
    row.querySelector(".account-msg").classList.toggle("error", s.flow === "failed");

    const actions = row.querySelector(".account-actions");
    const login = document.createElement("button");
    login.className = "small";
    login.textContent = s.logged_in ? "Re-login" : "Log in";
    login.disabled = inProgress;
    login.addEventListener("click", async () => {
      await api(`/api/auth/${s.site}/login`, { method: "POST" });
      refreshAccounts();
    });
    actions.appendChild(login);
    if (s.logged_in) {
      const logout = document.createElement("button");
      logout.className = "secondary small";
      logout.textContent = "Log out";
      logout.disabled = inProgress;
      logout.addEventListener("click", async () => {
        await api(`/api/auth/${s.site}/logout`, { method: "POST" });
        refreshAccounts();
      });
      actions.appendChild(logout);
    }
    box.appendChild(row);
  }
  if (busy) authTimer = setTimeout(refreshAccounts, 1500);
}

function renderSettings(s) {
  $("dl-dir").textContent = s.download_dir;
  $("dl-free").textContent = !s.available
    ? "(not available — is the drive plugged in?)"
    : s.free_bytes != null ? `· ${formatSize(s.free_bytes)} free` : "";
  $("dl-free").classList.toggle("error", !s.available);
  $("dl-dir-reset").classList.toggle("hidden", s.download_dir === s.default_download_dir);
  const box = $("dl-volumes");
  box.innerHTML = "";
  for (const vol of s.volumes) {
    const btn = document.createElement("button");
    btn.className = "secondary small";
    btn.textContent = `Use ${vol.name}`;
    btn.title = vol.target;
    btn.addEventListener("click", () => saveDownloadDir(vol.target));
    box.appendChild(btn);
  }
}

async function refreshSettings() {
  try {
    renderSettings(await api("/api/settings"));
  } catch {}
}

async function saveDownloadDir(path) {
  $("dl-dir-error").textContent = "";
  try {
    renderSettings(await api("/api/settings", { method: "POST", body: JSON.stringify({ download_dir: path }) }));
    $("dl-dir-input").value = "";
    refreshFiles();
  } catch (err) {
    $("dl-dir-error").textContent = err.message;
  }
}

$("dl-dir-save").addEventListener("click", () => {
  const path = $("dl-dir-input").value.trim();
  if (path) saveDownloadDir(path);
});
$("dl-dir-reset").addEventListener("click", () => saveDownloadDir(""));

$("target").addEventListener("input", updatePlatform);
$("platform").addEventListener("change", updatePlatform);
$("form").addEventListener("submit", submitForm);
$("refresh-files").addEventListener("click", refreshFiles);
$("open-folder").addEventListener("click", () =>
  api("/api/open-folder", { method: "POST" }).catch((err) => { $("dl-dir-error").textContent = err.message; }));

refreshAccounts();
refreshSettings();
refreshJobs();
refreshFiles();
setInterval(refreshJobs, 5000);
