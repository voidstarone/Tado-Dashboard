const REFRESH_MS = 30_000;
const zonesEl = document.getElementById("zones");
const statusEl = document.getElementById("status");
const tpl = document.getElementById("zone-card");

// Track cards by zone id so refreshes update in place (don't clobber inputs).
const cards = new Map();

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const body = await res.json().catch(() => ({}));
  if (res.status === 401 && body.error === "reauth_required") {
    enterReauth(body.verification_url);
    const err = new Error("reauthenticating");
    err.reauth = true;  // let callers skip the generic error toast
    throw err;
  }
  if (!res.ok) throw new Error(body.detail || body.error || res.statusText);
  return body;
}

const reauthEl = document.getElementById("reauth");
const reauthLink = document.getElementById("reauth-link");
const reauthMsg = document.getElementById("reauth-msg");
let reauthPolling = false;

// Show the device-code prompt and poll until the background login completes.
function enterReauth(url) {
  if (url) {
    reauthLink.href = url;
    reauthLink.textContent = url;
    reauthLink.hidden = false;
  }
  reauthEl.hidden = false;
  setStatus("Reconnecting to tado°…", true);
  if (!reauthPolling) {
    reauthPolling = true;
    pollAuth();
  }
}

async function pollAuth() {
  let state = {};
  try {
    state = await (await fetch("/api/auth/status")).json();
  } catch (_) {
    return void setTimeout(pollAuth, 3000);  // transient; keep trying
  }

  if (state.status === "ok") {
    reauthPolling = false;
    reauthEl.hidden = true;
    setStatus("Reconnected.");
    load();
    return;
  }
  if (state.status === "error") {
    reauthMsg.textContent =
      `Authentication failed: ${state.error || "unknown error"}. Retrying…`;
    load();  // re-triggers the backend, which starts a fresh device flow
  } else if (state.verification_url) {
    reauthLink.href = state.verification_url;
    reauthLink.textContent = state.verification_url;
    reauthLink.hidden = false;
  }
  setTimeout(pollAuth, 3000);
}

function fmt(v, digits = 1) {
  return (v === null || v === undefined) ? "–" : Number(v).toFixed(digits);
}

function renderZone(z) {
  let card = cards.get(z.id);
  if (!card) {
    card = tpl.content.firstElementChild.cloneNode(true);
    cards.set(z.id, card);
    zonesEl.appendChild(card);
    wireControls(card, z.id);
  }
  card.querySelector(".zone-name").textContent = z.name;
  card.querySelector(".cur-temp").textContent = fmt(z.current_temp);
  card.querySelector(".humidity").textContent = fmt(z.current_humidity, 0);
  card.querySelector(".heating").textContent = fmt(z.heating_power, 0);
  card.querySelector(".target-temp").textContent = fmt(z.target_temp);
  card.querySelector(".open-window").hidden = !z.open_window;

  const pill = card.querySelector(".mode-pill");
  pill.textContent = z.overlay_active ? "manual" : "schedule";

  // Only seed the input when the user isn't actively editing it.
  const input = card.querySelector(".set-temp");
  if (document.activeElement !== input && z.target_temp != null) {
    input.value = z.target_temp;
  }
}

function wireControls(card, zoneId) {
  const input = card.querySelector(".set-temp");
  card.querySelectorAll(".step").forEach((btn) =>
    btn.addEventListener("click", () => {
      const delta = parseFloat(btn.dataset.delta);
      input.value = (parseFloat(input.value || "20") + delta).toFixed(1);
    })
  );
  card.querySelector(".set").addEventListener("click", async () => {
    try {
      setStatus("Setting…");
      await api(`/api/zones/${zoneId}/temperature`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ temp: parseFloat(input.value) }),
      });
      await load();
    } catch (e) {
      if (!e.reauth) setStatus(`Error: ${e.message}`, true);
    }
  });
  card.querySelector(".auto").addEventListener("click", async () => {
    try {
      setStatus("Resuming schedule…");
      await api(`/api/zones/${zoneId}/auto`, { method: "POST" });
      await load();
    } catch (e) {
      if (!e.reauth) setStatus(`Error: ${e.message}`, true);
    }
  });
}

async function load() {
  try {
    const { zones } = await api("/api/zones");
    zones.forEach(renderZone);
    if (zonesEl.querySelector(".loading")) {
      zonesEl.querySelector(".loading").remove();
    }
    setStatus(`Updated ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    if (!e.reauth) setStatus(`Error: ${e.message}`, true);
  }
}

load();
setInterval(load, REFRESH_MS);
