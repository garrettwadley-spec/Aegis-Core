import json
import os

MEMORY_FILE = "aegis/memory/strategy_results.json"


def save_results(results):
    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "w") as f:
            json.dump([], f)

    with open(MEMORY_FILE, "r") as f:
        data = json.load(f)

    data.extend(results)

    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f, indent=2)