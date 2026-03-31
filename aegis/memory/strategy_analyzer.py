import json

MEMORY_FILE = "aegis/memory/strategy_results.json"


def load_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except:
        return []


def get_top_strategies(n=10):
    data = load_memory()

    sorted_data = sorted(
        data,
        key=lambda x: x["performance"].get("sharpe", 0),
        reverse=True
    )

    return sorted_data[:n]


def extract_param_ranges(top_strategies):
    fast_vals = []
    slow_vals = []

    for item in top_strategies:
        params = item["performance"]["params"]
        fast_vals.append(params["sma_fast"])
        slow_vals.append(params["sma_slow"])

    return {
        "fast_min": min(fast_vals),
        "fast_max": max(fast_vals),
        "slow_min": min(slow_vals),
        "slow_max": max(slow_vals),
    }