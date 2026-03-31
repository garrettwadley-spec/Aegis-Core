def risk_simulate(position_usd=10000, vol=0.2):
    return {"var_95": round(position_usd*vol*1.65/100, 2), "inputs":{"position_usd":position_usd,"vol":vol}}
