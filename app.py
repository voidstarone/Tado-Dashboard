"""Flask web dashboard for tado thermostats: read state + set temperatures."""
from flask import Flask, jsonify, render_template, request
from PyTado.exceptions import TadoCredentialsException

from tado_client import TadoService, ReauthRequired

app = Flask(__name__)
service = TadoService()


def _reauth_response():
    """401 carrying the device-code verification URL so the UI can prompt the
    user to re-approve. The service has already started the flow."""
    state = service.auth_state()
    return jsonify({
        "error": "reauth_required",
        "detail": "Tado login expired — approve the device to reconnect.",
        "verification_url": state.get("verification_url"),
        "auth_status": state.get("status"),
    }), 401


def _guard(fn):
    """Run a service call, mapping auth failures to a reauth prompt and other
    library errors to a 502."""
    try:
        return fn()
    except (ReauthRequired, TadoCredentialsException):
        return _reauth_response()
    except Exception as e:  # surface other tado/library errors to the UI
        return jsonify({"error": "tado_error", "detail": str(e)}), 502


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/status")
def api_auth_status():
    """Lets the frontend poll the device-code login while it's pending."""
    return jsonify(service.auth_state())


@app.route("/api/zones")
def api_zones():
    return _guard(lambda: jsonify({"zones": service.get_zones()}))


@app.route("/api/zones/<int:zone_id>/temperature", methods=["POST"])
def api_set_temp(zone_id):
    data = request.get_json(silent=True) or {}
    temp = data.get("temp")
    if temp is None:
        return jsonify({"error": "bad_request", "detail": "temp is required"}), 400
    duration = data.get("duration_seconds")  # optional; None = until changed

    def op():
        service.set_temperature(zone_id, float(temp), duration)
        return jsonify({"ok": True})
    return _guard(op)


@app.route("/api/zones/<int:zone_id>/auto", methods=["POST"])
def api_resume(zone_id):
    def op():
        service.resume_schedule(zone_id)
        return jsonify({"ok": True})
    return _guard(op)


if __name__ == "__main__":
    # Bind to localhost by default; change host/port as needed.
    app.run(host="127.0.0.1", port=6767)
