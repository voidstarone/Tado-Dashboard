"""One-time device-code pairing with tado.

Run this once before starting the server:

    python auth.py

It prints a verification URL (and tries to open your browser). Approve the
login at that URL within 5 minutes. On success a refresh token is written to
tado_token.json and reused by the server. Refresh tokens last ~30 days; as long
as the server runs (or you re-auth) within that window you won't need to repeat
this.
"""
import sys
import webbrowser

from tado_client import new_tado, TOKEN_FILE


def main():
    tado = new_tado()
    status = tado.device_activation_status()

    if status == "PENDING":
        url = tado.device_verification_url()
        print("\nGo to this URL in a browser and approve the login:\n")
        print(f"    {url}\n")
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass
        print("Waiting for approval (times out in 5 minutes)...")
        tado.device_activation()  # blocks/polls until approved or timeout
        status = tado.device_activation_status()

    if status == "COMPLETED":
        print(f"\n✅ Authenticated. Token saved to {TOKEN_FILE}")
        return 0

    print(f"\n❌ Authentication did not complete (status: {status}).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
