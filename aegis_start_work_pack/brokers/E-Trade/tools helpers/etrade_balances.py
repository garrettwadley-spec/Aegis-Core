import os
import json
import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv

load_dotenv(r"C:\AITrader\.env")

BASE = "https://apisb.etrade.com"
ACCOUNT_KEY = os.getenv("ETRADE_ACCOUNT_ID")

auth = OAuth1(
    os.getenv("ETRADE_API_KEY"),
    client_secret=os.getenv("ETRADE_API_SECRET"),
    resource_owner_key=os.getenv("ETRADE_ACCESS_TOKEN"),
    resource_owner_secret=os.getenv("ETRADE_ACCESS_SECRET"),
    signature_method="HMAC-SHA1",
)

url = f"{BASE}/v1/accounts/{ACCOUNT_KEY}/balance.json?instType=BROKERAGE&realTimeNAV=true"

r = requests.get(
    url,
    auth=auth,
    headers={"Accept": "application/json"},
)

print("HTTP Status:", r.status_code)
print("Response Preview:")
print(r.text[:3000])

try:
    print(json.dumps(r.json(), indent=2))
except Exception:
    pass