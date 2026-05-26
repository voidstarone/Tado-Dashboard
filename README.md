# tado° web dashboard

A small Flask dashboard for tado° heating: shows current temperature, humidity,
heating power and setpoint per room, and lets you set a target temperature or
resume the smart schedule.

Built on [`python-tado`](https://pypi.org/project/python-tado/), which handles
tado's OAuth2 **device code flow** (the username/password flow was removed by
tado in March 2025).

## Setup

```bash
cd tado-dashboard
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 1. Run the dashboard

```bash
python app.py
```

Open <http://127.0.0.1:6767>. It auto-refreshes every 30s.

This serves via [waitress](https://pypi.org/project/waitress/) (a production
WSGI server) when it's installed — no dev-server warning — and falls back to
Flask's dev server otherwise. It binds to `0.0.0.0`, so other devices on your
LAN can reach it at `http://<this-machine-ip>:6767`.

> **Run it as a single process.** `TadoService` keeps the tado° connection, auth
> state, and the background reauth thread in memory. Waitress uses one process
> with a thread pool, which is exactly right. Do **not** switch to a
> multi-worker/-process server (e.g. `gunicorn -w 4`) — each worker would get
> its own token client and they'd fight over the rotating refresh token (see
> below). One process, many threads: fine. Many processes: breaks auth.

**First run / re-login is handled in the browser.** If there's no valid token,
the dashboard shows a banner with a tado° approval link. Click it, approve the
device (within ~5 min), and the page reconnects automatically — no restart
needed. A refresh token is saved to `tado_token.json`.

> You can also pair from the terminal instead with `python auth.py` (same device
> flow). Do this **only while the server is stopped** — see the rotating-token
> note below.

> **Keep `tado_token.json` private** — it grants control of your heating.

## How auth stays alive

tado° uses **single-use rotating refresh tokens**: every refresh issues a new
token and invalidates the old one. The running server keeps the live token in
memory and rewrites the file on each refresh, so it's self-consistent on its
own. The catch: if a *second* client touches the same token file (a stray
`auth.py` run, a duplicate server, the Flask debug reloader), it rotates the
token out from under the server, and the server's next refresh fails with a
`403`.

The app now self-heals — when a refresh fails it automatically restarts the
device-code flow and surfaces the approval link in the UI (`GET /api/auth/status`
exposes the state). To avoid the situation entirely: **run only one Tado client
against `tado_token.json` at a time**, and leave `debug=False` in `app.py` (set)
so the reloader doesn't spawn a second process.

## Notes & caveats

- **Unofficial API.** tado tolerates but doesn't formally support third-party
  use; endpoints can change (as the 2025 auth change showed). The `python-tado`
  library insulates you from most of that — keep it updated.
- **Units.** Temperatures are shown/sent in your home's configured unit (°C or
  °F). The input range in the UI assumes °C; adjust `static/index.html` if you
  use °F.
- **Setting temperature** creates a *manual overlay* that lasts until you change
  it (or hit **Auto**). To make it expire after a time instead, pass
  `duration_seconds` in the POST body — `set_temperature` already supports it.
- **Cooling / AC zones.** The overlay calls assume `device_type="HEATING"`.
  Adjust `tado_client.py` for AC zones.
- **Exposure.** It binds to `127.0.0.1`. Don't expose it to the internet without
  adding authentication and HTTPS in front.

## Files

| File | Purpose |
|------|---------|
| `auth.py` | Optional CLI device-code pairing → `tado_token.json` (the app also pairs/re-pairs in the browser) |
| `tado_client.py` | PyTado wrapper: zones, state, set/resume overlay, self-healing reauth |
| `app.py` | Flask server + JSON API (incl. `GET /api/auth/status`) |
| `templates/index.html`, `static/` | Frontend |
