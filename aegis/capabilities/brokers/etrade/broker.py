import os
import requests
from requests_oauthlib import OAuth1
from dotenv import load_dotenv


class ETradeBroker:
    def __init__(self):
        load_dotenv(r"C:\AITrader\.env")

        self.env = os.getenv("ETRADE_ENV", "sandbox").lower()
        self.base = "https://apisb.etrade.com" if self.env == "sandbox" else "https://api.etrade.com"
        self.account_key = os.getenv("ETRADE_ACCOUNT_ID")

        self.auth = OAuth1(
            os.getenv("ETRADE_API_KEY"),
            client_secret=os.getenv("ETRADE_API_SECRET"),
            resource_owner_key=os.getenv("ETRADE_ACCESS_TOKEN"),
            resource_owner_secret=os.getenv("ETRADE_ACCESS_SECRET"),
            signature_method="HMAC-SHA1",
        )

    def _get(self, path, params=None):
        url = f"{self.base}{path}"
        r = requests.get(url, auth=self.auth, params=params, headers={"Accept": "application/json"})
        return self._handle_response(r)

    def _post(self, path, payload):
        url = f"{self.base}{path}"
        r = requests.post(url, auth=self.auth, json=payload, headers={"Accept": "application/json"})
        return self._handle_response(r)

    def _handle_response(self, response):
        result = {
            "status_code": response.status_code,
            "ok": response.ok,
            "raw": response.text,
            "raw_preview": response.text[:1000],
        }

        try:
            result["json"] = response.json()
        except Exception:
            result["json"] = None

        return result

    def accounts(self):
        return self._get("/v1/accounts/list")

    def quote(self, symbol):
        return self._get(f"/v1/market/quote/{symbol}.json")

    def positions(self):
        return self._get(f"/v1/accounts/{self.account_key}/portfolio.json")

    def balances(self):
        return self._get(
            f"/v1/accounts/{self.account_key}/balance.json",
            params={"instType": "BROKERAGE", "realTimeNAV": "true"},
        )

    def orders(self):
        return self._get(f"/v1/accounts/{self.account_key}/orders.json")

    def preview_equity_order(self, symbol, quantity, action="BUY"):
        payload = {
            "PreviewOrderRequest": {
                "orderType": "EQ",
                "clientOrderId": f"AEGIS_PREVIEW_{symbol}_{quantity}_{action}",
                "Order": [{
                    "allOrNone": False,
                    "priceType": "MARKET",
                    "orderTerm": "GOOD_FOR_DAY",
                    "marketSession": "REGULAR",
                    "Instrument": [{
                        "quantity": quantity,
                        "Product": {
                            "securityType": "EQ",
                            "symbol": symbol
                        },
                        "orderAction": action
                    }]
                }]
            }
        }

        return self._post(
            f"/v1/accounts/{self.account_key}/orders/preview",
            payload
        )