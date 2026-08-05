"""One-time bootstrap: run the Monzo OAuth2 authorization-code flow locally
and store the resulting refresh token in Key Vault.
"""
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests

from kv import get_secret, set_secret

CLIENT_ID = get_secret("monzo-client-id")
CLIENT_SECRET = get_secret("monzo-client-secret")
REDIRECT_URI = os.environ.get("MONZO_REDIRECT_URI", "http://localhost:5000/callback")

result = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        result["code"] = params.get("code", [None])[0]
        result["state"] = params.get("state", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Authorised - you can close this tab and return to the terminal.")

    def log_message(self, format, *args):
        pass


def main():
    state = secrets.token_urlsafe(16)
    auth_url = "https://auth.monzo.com/?" + urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "state": state,
    })

    print(f"Opening browser for Monzo authorisation:\n{auth_url}\n")
    webbrowser.open(auth_url)

    port = int(urlparse(REDIRECT_URI).port or 5000)
    server = HTTPServer(("localhost", port), CallbackHandler)
    print("Waiting for redirect...")
    server.handle_request()

    if result.get("state") != state:
        raise SystemExit("State mismatch on callback - possible CSRF, aborting.")
    if not result.get("code"):
        raise SystemExit("No authorisation code received.")

    token_response = requests.post("https://api.monzo.com/oauth2/token", data={
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": result["code"],
    })
    token_response.raise_for_status()
    tokens = token_response.json()

    print("\nAccess token acquired.")
    print("Now open the Monzo app - you should see a request to confirm access for this client.")
    input("Press Enter once you've approved it in the app...")

    set_secret("monzo-refresh-token", tokens["refresh_token"])
    print("Refresh token stored in Key Vault.")


if __name__ == "__main__":
    main()
