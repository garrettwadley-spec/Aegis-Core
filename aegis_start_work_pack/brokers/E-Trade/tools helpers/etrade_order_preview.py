import os
import json
import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv

load_dotenv(r"C:\AITrader\.env")

BASE = "https://apisb.etrade.com"

ACCOUNT_KEY = "vQMsebA1H5WltUfDkJP48g"

auth = OAuth1(
    os.getenv("ETRADE_API_KEY"),
    client_secret=os.getenv("ETRADE_API_SECRET"),
    resource_owner_key=os.getenv("ETRADE_ACCESS_TOKEN"),
    resource_owner_secret=os.getenv("ETRADE_ACCESS_SECRET"),
    signature_method="HMAC-SHA1",
)

url = f"{BASE}/v1/accounts/{ACCOUNT_KEY}/orders/preview"

payload = {
    "PreviewOrderRequest": {
        "orderType": "EQ",
        "clientOrderId": "AEGIS_TEST_001",
        "Order": [{
            "allOrNone": False,
            "priceType": "MARKET",
            "orderTerm": "GOOD_FOR_DAY",
            "marketSession": "REGULAR",
            "Instrument": [{
                "quantity": 1,
                "Product": {
                    "securityType": "EQ",
                    "symbol": "SPY"
                },
                "orderAction": "BUY"
            }]
        }]
    }
}

r = requests.post(
    url,
    auth=auth,
    json=payload,
    headers={"Accept": "application/json"}
)

print("HTTP Status:", r.status_code)
print(r.text)