import os, json, sys, time, webbrowser
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

# E*TRADE uses the sandbox/prod API host for token + API calls.
API_BASE = "https://apisb.etrade.com" if ENV == "sandbox" else "https://api.etrade.com"

# The authorize page is the E*TRADE web-login page, not the API host.
REQ_TOKEN = f"{API_BASE}/oauth/request_token"
AUTH = "https://us.etrade.com/e/t/etws/authorize"
ACCESS = f"{API_BASE}/oauth/access_token"
ACCOUNTS = f"{API_BASE}/v1/accounts/list"

CK = os.getenv("ETRADE_API_KEY")
CS = os.getenv("ETRADE_API_SECRET")

# For manual PIN/verifier mode, use "oob".
# If .env is blank, default to "oob" instead of sending an empty callback.
CB = (os.getenv("ETRADE_CALLBACK_URL") or "oob").strip()


def oauth1(t=None, s=None, cb=None):
    return OAuth1(
        CK,
        client_secret=CS,
        resource_owner_key=t,
        resource_owner_secret=s,
        callback_uri=cb,
        signature_method="HMAC-SHA1",
    )


def get_req():
    print(f"Requesting token from: {REQ_TOKEN}")
    print(f"Callback mode: {CB}")
    r = requests.post(REQ_TOKEN, auth=oauth1(cb=CB))
    if r.status_code >= 400:
        print("\nRequest token failed.")
        print("HTTP status:", r.status_code)
        print("Response body:", r.text[:1000])
        r.raise_for_status()
    q = parse_qs(r.text)
    return q["oauth_token"][0], q["oauth_token_secret"][0]


def open_auth(t):
    url = f"{AUTH}?key={CK}&token={t}"
    print("\nAuthorize URL:", url)
    try:
        webbrowser.open(url)
    except Exception:
        pass


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        v = q.get("oauth_verifier", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK; you can close this window.")
        self.server.verifier = v


def capture(port=5050, timeout=300):
    s = HTTPServer(("127.0.0.1", port), H)
    s.verifier = None
    end = time.time() + timeout
    while time.time() < end and not s.verifier:
        s.handle_request()
    return s.verifier

def get_access(rt, rs, v):
    r = requests.post(
        ACCESS,
        auth=OAuth1(
            CK,
            client_secret=CS,
            resource_owner_key=rt,
            resource_owner_secret=rs,
            verifier=v,
            signature_method="HMAC-SHA1",
        ),
    )

    if r.status_code >= 400:
        print("\nAccess token failed.")
        print("HTTP status:", r.status_code)
        print("Response body:", r.text[:1000])
        r.raise_for_status()

    q = parse_qs(r.text)
    return q["oauth_token"][0], q["oauth_token_secret"][0]



def fetch_accounts(at, asecret):
    r = requests.get(
        ACCOUNTS,
        auth=OAuth1(
            CK,
            client_secret=CS,
            resource_owner_key=at,
            resource_owner_secret=asecret,
            signature_method="HMAC-SHA1",
        ),
        headers={"Accept": "application/json"},
    )

    print("Accounts HTTP status:", r.status_code)
    print("Accounts response preview:", r.text[:1000])

    r.raise_for_status()

    try:
        return r.json()
    except Exception:
        return {"raw_response": r.text}


def main():
    if not CK or not CS:
        print("Set ETRADE_API_KEY and ETRADE_API_SECRET.")
        sys.exit(1)

    print(f"E*TRADE get accounts ({ENV.upper()})")
    rt, rs = get_req()
    open_auth(rt)

    v = None
    if CB and CB.lower() != "oob" and ("127.0.0.1" in CB or "localhost" in CB):
        port = urlparse(CB).port or 80
        v = capture(port=port, timeout=300)

    if not v:
        v = input("Paste oauth_verifier / verification code from E*TRADE: ").strip()

    at, as_ = get_access(rt, rs, v)
    data = fetch_accounts(at, as_)

    try:
        accounts = data["AccountListResponse"]["Accounts"]["Account"]
    except Exception:
        print("Unexpected response:", json.dumps(data, indent=2))
        sys.exit(1)

    out = [
        {k: acc.get(k) for k in ("accountId", "accountIdKey", "accountDesc", "institutionType", "accountMode")}
        for acc in accounts
    ]

    print("\n=== Accounts ===")
    for a in out:
        print(a)

    os.makedirs("config", exist_ok=True)
    with open("config/accounts.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("\nSaved: config/accounts.json")
    if out:
        print("\nUse accountIdKey below in .env:")
        print("ETRADE_ACCOUNT_ID=" + out[0]["accountIdKey"])

    print("\nAlso set in .env:")
    print("ETRADE_ACCESS_TOKEN=" + at)
    print("ETRADE_ACCESS_SECRET=" + as_)


if __name__ == "__main__":
    main()
