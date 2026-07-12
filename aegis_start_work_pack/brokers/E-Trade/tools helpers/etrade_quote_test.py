import os
import json
import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv

load_dotenv(r"C:\AITrader\.env")

ENV = os.getenv("ETRADE_ENV", "sandbox")

BASE = (
    "https://apisb.etrade.com"
    if ENV == "sandbox"
    else "https://api.etrade.com"
)

auth = OAuth1(
    os.getenv("ETRADE_API_KEY"),
    client_secret=os.getenv("ETRADE_API_SECRET"),
    resource_owner_key=os.getenv("ETRADE_ACCESS_TOKEN"),
    resource_owner_secret=os.getenv("ETRADE_ACCESS_SECRET"),
    signature_method="HMAC-SHA1",
)

url = f"{BASE}/v1/market/quote/SPY.json"

r = requests.get(url, auth=auth)

print("HTTP Status:", r.status_code)
print(json.dumps(r.json(), indent=2))