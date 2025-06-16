import http.server
import socketserver
import threading
import webbrowser
import urllib.parse
import requests
import os
from dotenv import load_dotenv, set_key

# Load environment variables from .env
load_dotenv()

# === Config ===
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_PORT = 8080
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPES = "openid email profile"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
ENV_PATH = ".env"

# === Global store for the code ===
auth_code_holder = {"code": None}


class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query_params = urllib.parse.parse_qs(parsed_path.query)

        if "code" in query_params:
            auth_code_holder["code"] = query_params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization successful!</h1>You can close this window.")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Error: No code received.</h1>")


def start_local_server():
    httpd = socketserver.TCPServer(("localhost", REDIRECT_PORT), OAuthHandler)
    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()
    return httpd


def refresh_tokens(refresh_token):
    print("Attempting to refresh tokens using refresh_token...")
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    resp = requests.post(TOKEN_URL, data=data)
    if resp.status_code != 200:
        print("Refresh token request failed:", resp.text)
        return None
    return resp.json()


def exchange_code_for_tokens(code):
    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    resp = requests.post(TOKEN_URL, data=data)
    if resp.status_code != 200:
        print("Failed to exchange code for tokens:", resp.text)
        return None
    return resp.json()


def save_tokens(tokens):
    id_token = tokens.get("id_token")
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")  # might be None if not returned again

    # Use python-dotenv's set_key to update or add values in .env
    if id_token:
        set_key(ENV_PATH, "GOOGLE_ID_TOKEN", id_token)
    if access_token:
        set_key(ENV_PATH, "GOOGLE_OAUTH2_ACCESS_TOKEN", access_token)
    if refresh_token:
        set_key(ENV_PATH, "GOOGLE_OAUTH2_REFRESH_TOKEN", refresh_token)

    print("\nTokens saved to .env")
    print("Access Token:", access_token)
    print("ID Token:", id_token)
    if refresh_token:
        print("Refresh Token saved/updated.")


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env")

    # Try to load existing refresh token from env
    refresh_token = os.getenv("GOOGLE_OAUTH2_REFRESH_TOKEN")

    tokens = None

    if refresh_token:
        tokens = refresh_tokens(refresh_token)

    if tokens is None:
        # No valid refresh token or refresh failed → do full OAuth flow
        httpd = start_local_server()

        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent"
        }
        auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
        print(f"Opening browser to authenticate...\n{auth_url}")
        webbrowser.open(auth_url)

        print("Waiting for Google redirect with authorization code...")
        while auth_code_holder["code"] is None:
            pass  # busy wait (safe here since local and fast)

        httpd.shutdown()

        code = auth_code_holder["code"]
        print(f"\n✅ Authorization code received:\n{code}")

        tokens = exchange_code_for_tokens(code)
        if tokens is None:
            print("❌ Could not get tokens, exiting.")
            return

    save_tokens(tokens)


if __name__ == "__main__":
    main()
