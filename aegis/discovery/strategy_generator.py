import random
from aegis.memory.strategy_analyzer import get_top_strategies, extract_param_ranges


def generate_batch(size=10):
    top = get_top_strategies(20)

    if top:
        ranges = extract_param_ranges(top)

        fast_min = max(2, ranges["fast_min"] - 5)
        fast_max = ranges["fast_max"] + 5

        slow_min = max(fast_max + 1, ranges["slow_min"] - 20)
        slow_max = ranges["slow_max"] + 20
    else:
        fast_min, fast_max = 5, 20
        slow_min, slow_max = 20, 200

    strategies = []

    for _ in range(size):
        fast = random.randint(fast_min, fast_max)
        slow = random.randint(max(fast + 1, slow_min), slow_max)

        strategies.append({
            "fast": fast,
            "slow": slow
        })

    return strategies