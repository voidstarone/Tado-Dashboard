"""Thin wrapper around python-tado (PyTado).

Centralizes the import path, a process-wide lock (PyTado isn't thread-safe and
Flask's dev server is threaded), and helpers to normalize zone state into plain
dicts the frontend can consume.
"""
import os
import threading

# PyTado moved the Tado class around between versions; support both.
try:
    from PyTado.interface.interface import Tado
except ImportError:  # older layout
    from PyTado.interface import Tado

from PyTado.const import (
    CONST_OVERLAY_MANUAL,
    CONST_OVERLAY_TIMER,
)
from PyTado.exceptions import TadoCredentialsException

TOKEN_FILE = os.environ.get(
    "TADO_TOKEN_FILE",
    os.path.join(os.path.dirname(__file__), "tado_token.json"),
)


class ReauthRequired(Exception):
    """Raised when the stored Tado credentials are gone/stale and a fresh
    device-code login is needed. The service has already started the flow; the
    verification URL is available via TadoService.auth_state()."""


def new_tado():
    """Instantiate Tado bound to the token file. With a valid token it comes up
    COMPLETED; with no token it starts (PENDING) a device flow; with a stale
    token the refresh fails and it stays NOT_STARTED (unusable)."""
    return Tado(token_file_path=TOKEN_FILE)


def _attr(obj, name, default=None):
    """TadoZone exposes state as properties; tolerate version differences."""
    return getattr(obj, name, default)


def zone_to_dict(zone, state):
    """Combine a zone (id/name) with its TadoZone state into a flat dict."""
    return {
        "id": zone["id"],
        "name": zone["name"],
        "current_temp": _attr(state, "current_temp"),
        "current_humidity": _attr(state, "current_humidity"),
        "target_temp": _attr(state, "target_temp"),
        "heating_power": _attr(state, "heating_power_percentage"),
        "power": _attr(state, "power"),                 # "ON" / "OFF"
        "open_window": bool(_attr(state, "open_window", False)),
        "overlay_active": bool(_attr(state, "overlay_active", False)),
        "hvac_action": _attr(state, "current_hvac_action"),
    }


class TadoService:
    """Tado connection that serializes API access and self-heals auth.

    Tado uses single-use rotating refresh tokens, so a token can go stale while
    the server runs (e.g. another client refreshed it). When that happens we
    kick off a device-code login in a background thread and expose the
    verification URL through auth_state() so the UI can prompt the user; calls
    raise ReauthRequired until the user approves.
    """

    def __init__(self):
        self._tado = None
        self._api_lock = threading.Lock()   # serializes PyTado calls (not thread-safe)
        self._auth_lock = threading.Lock()  # guards _tado + _auth + flow startup
        self._auth = {"status": "starting", "verification_url": None, "error": None}
        self._reauth_thread = None

    # --- auth lifecycle -----------------------------------------------------

    def auth_state(self):
        """Snapshot of the auth state for the frontend: status is one of
        starting | ok | authenticating | error."""
        with self._auth_lock:
            return dict(self._auth)

    def is_authenticated(self):
        return self.auth_state()["status"] == "ok"

    def _connected(self):
        """Return a COMPLETED Tado connection, establishing one if possible.
        Starts a device flow and raises ReauthRequired if credentials are
        missing/stale. Fully serialized so only one Tado client is ever built
        (concurrent builds would fight over the rotating refresh token)."""
        with self._auth_lock:
            if self._auth["status"] == "ok" and self._tado is not None:
                return self._tado
            if self._auth["status"] == "authenticating":
                raise ReauthRequired()

            tado = new_tado()
            if str(tado.device_activation_status()) == "COMPLETED":
                self._tado = tado
                self._auth = {"status": "ok", "verification_url": None, "error": None}
                return self._tado

            # No usable token: begin a device-code flow (still holding the lock).
            self._start_device_flow(tado)
            raise ReauthRequired()

    def _start_device_flow(self, tado):
        """Begin device-code login and poll for approval in a daemon thread.
        Caller must hold _auth_lock."""
        if self._auth["status"] == "authenticating":
            return  # a flow is already running
        # A stale (NOT_STARTED) instance can't drive a flow; move the dead token
        # aside and build a fresh client that comes up PENDING.
        if str(tado.device_activation_status()) != "PENDING":
            if os.path.exists(TOKEN_FILE):
                os.replace(TOKEN_FILE, TOKEN_FILE + ".stale")
            tado = new_tado()

        if str(tado.device_activation_status()) != "PENDING":
            self._auth = {"status": "error", "verification_url": None,
                          "error": "could not start device authentication"}
            return

        self._tado = None
        self._auth = {
            "status": "authenticating",
            "verification_url": tado.device_verification_url(),
            "error": None,
        }
        self._reauth_thread = threading.Thread(
            target=self._activate, args=(tado,), daemon=True
        )
        self._reauth_thread.start()

    def _activate(self, tado):
        """Block until the user approves the login (or it times out), then
        publish the result. Holds no lock while polling."""
        try:
            tado.device_activation()  # blocks, sleeping between polls
        except Exception as e:  # timeout, network, denied — surface to the UI
            with self._auth_lock:
                self._auth = {"status": "error", "verification_url": None,
                              "error": str(e)}
            return
        with self._auth_lock:
            self._tado = tado
            self._auth = {"status": "ok", "verification_url": None, "error": None}

    def _call(self, fn):
        """Run fn(tado) under the API lock, healing stale credentials by
        starting a reauth flow and raising ReauthRequired."""
        tado = self._connected()
        try:
            with self._api_lock:
                return fn(tado)
        except TadoCredentialsException:
            with self._auth_lock:
                self._tado = None
                self._start_device_flow(new_tado())
            raise ReauthRequired()

    # --- operations ---------------------------------------------------------

    def get_zones(self):
        def op(tado):
            out = []
            for z in tado.get_zones():
                state = tado.get_zone_state(z["id"])
                out.append(zone_to_dict(z, state))
            return out
        return self._call(op)

    def set_temperature(self, zone_id, temp, duration_seconds=None):
        """Set a manual overlay. duration_seconds=None -> until manually changed."""
        def op(tado):
            if duration_seconds:
                tado.set_zone_overlay(
                    zone=zone_id,
                    overlay_mode=CONST_OVERLAY_TIMER,
                    set_temp=temp,
                    duration=duration_seconds,
                    device_type="HEATING",
                )
            else:
                tado.set_zone_overlay(
                    zone=zone_id,
                    overlay_mode=CONST_OVERLAY_MANUAL,
                    set_temp=temp,
                    device_type="HEATING",
                )
        return self._call(op)

    def resume_schedule(self, zone_id):
        """Clear the overlay so the zone follows its smart schedule again."""
        return self._call(lambda tado: tado.reset_zone_overlay(zone_id))
