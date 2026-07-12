# tools/etrade_api.py
import os
import requests
from requests_oauthlib import OAuth1

try:
    from dotenv import load_dotenv
    load_dotenv(r"C:\AITrader\.env")
except Exception:
    pass

BASE_URLS = {
    "sandbox": "https://apisb.etrade.com",
    "live": "https://api.etrade.com",
}

def oauth_session():
    return OAuth1(
        os.getenv("ETRADE_API_KEY"),
        client_secret=os.getenv("ETRADE_API_SECRET"),
        resource_owner_key=os.getenv("ETRADE_ACCESS_TOKEN"),
        resource_owner_secret=os.getenv("ETRADE_ACCESS_SECRET"),
        signature_method="HMAC-SHA1",
    )

def get_accounts():
    env = os.getenv("ETRADE_ENV", "sandbox").lower().strip()
    base = BASE_URLS[env]
    url = f"{base}/v1/accounts/list"

    r = requests.get(
        url,
        auth=oauth_session(),
        headers={"Accept": "application/json"},
    )

    print("HTTP status:", r.status_code)
    print("Response preview:", r.text[:500])

    r.raise_for_status()
    return r.json()