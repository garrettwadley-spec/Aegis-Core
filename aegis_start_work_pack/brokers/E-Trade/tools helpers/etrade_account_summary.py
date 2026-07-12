import json
import etrade_api

data = etrade_api.get_accounts()

accounts = data["AccountListResponse"]["Accounts"]["Account"]

print("\n=== ACCOUNT SUMMARY ===\n")

for acct in accounts:
    print(f"Name       : {acct.get('accountName')}")
    print(f"Desc       : {acct.get('accountDesc')}")
    print(f"Type       : {acct.get('accountType')}")
    print(f"Mode       : {acct.get('accountMode')}")
    print(f"Status     : {acct.get('accountStatus')}")
    print(f"Account ID : {acct.get('accountId')}")
    print(f"AccountKey : {acct.get('accountIdKey')}")
    print("-" * 60)