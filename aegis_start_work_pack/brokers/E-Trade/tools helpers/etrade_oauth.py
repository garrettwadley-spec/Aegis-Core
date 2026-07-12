import os, sys, time, webbrowser
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from requests_oauthlib import OAuth1

try:
    from dotenv import load_dotenv
    load_dotenv(r"C:\AITrader\.env")
except Exception:
    pass

ENV = os.getenv("ETRADE_ENV", "sandbox").lower().strip()

# E*TRADE uses the sandbox/prod API host for token calls.
API_BASE = "https://apisb.etrade.com" if ENV == "sandbox" else "https://api.etrade.com"

# The authorize page is the E*TRADE web-login page, not the API host.
REQ_TOKEN_URL = f"{API_BASE}/oauth/request_token"
AUTH_URL = "https://us.etrade.com/e/t/etws/authorize"
ACCESS_URL = f"{API_BASE}/oauth/access_token"

CK = os.getenv("ETRADE_API_KEY")
CS = os.getenv("ETRADE_API_SECRET")

# For manual PIN/verifier mode, use "oob".
# If .env is blank, default to "oob" instead of sending an empty callback.
CB = (os.getenv("ETRADE_CALLBACK_URL") or "oob").strip()


def oauth1(token=None, secret=None, cb=None):
    return OAuth1(
        CK,
        client_secret=CS,
        resource_owner_key=token,
        resource_owner_secret=secret,
        callback_uri=cb,
        signature_method="HMAC-SHA1",
    )


def get_request_token():
    print(f"Requesting token from: {REQ_TOKEN_URL}")
    print(f"Callback mode: {CB}")
    r = requests.post(REQ_TOKEN_URL, auth=oauth1(cb=CB))
    if r.status_code >= 400:
        print("\nRequest token failed.")
        print("HTTP status:", r.status_code)
        print("Response body:", r.text[:1000])
        r.raise_for_status()
    q = parse_qs(r.text)
    return q["oauth_token"][0], q["oauth_token_secret"][0]


def open_auth(t):
    url = f"{AUTH_URL}?key={CK}&token={t}"
    print("\nAuthorize URL:", url)
    try:
        webbrowser.open(url)
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        v = q.get("oauth_verifier", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK; you can close this window.")
        self.server.verifier = v


def capture_verifier(port=5050, timeout=300):
    server = HTTPServer(("127.0.0.1", port), Handler)
    server.verifier = None
    end = time.time() + timeout
    while time.time() < end and not server.verifier:
        server.handle_request()
    return server.verifier


def get_access(rt, rs, verifier):
    r = requests.post(ACCESS_URL, auth=oauth1(rt, rs), data={"oauth_verifier": verifier})
    if r.status_code >= 400:
        print("\nAccess token failed.")
        print("HTTP status:", r.status_code)
        print("Response body:", r.text[:1000])
        r.raise_for_status()
    q = parse_qs(r.text)
    return q["oauth_token"][0], q["oauth_token_secret"][0]


def main():
    if not CK or not CS:
        print("Set ETRADE_API_KEY and ETRADE_API_SECRET.")
        sys.exit(1)

    print(f"E*TRADE OAuth ({ENV.upper()})")
    rt, rs = get_request_token()
    open_auth(rt)

    v = None
    if CB and CB.lower() != "oob" and ("127.0.0.1" in CB or "localhost" in CB):
        port = urlparse(CB).port or 80
        v = capture_verifier(port=port, timeout=300)

    if not v:
        v = input("Paste oauth_verifier / verification code from E*TRADE: ").strip()

    at, as_ = get_access(rt, rs, v)
    print("ETRADE_ACCESS_TOKEN=" + at)
    print("ETRADE_ACCESS_SECRET=" + as_)


if __name__ == "__main__":
    main()
