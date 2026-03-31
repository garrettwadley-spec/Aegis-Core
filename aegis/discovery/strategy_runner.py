from aegis.discovery.strategy_generator import generate_batch
from aegis.tools.backtest_run import backtest_run
from aegis.memory.strategy_memory import save_results


def run_discovery(batch_size=10):
    strategies = generate_batch(batch_size)

    results = []

    for strat in strategies:
        try:
            result = backtest_run(
                strategy="sma",
                symbols="SPY",
                params={
                    "sma_fast": strat["fast"],
                    "sma_slow": strat["slow"]
                }
            )

            results.append({
                "strategy": strat,
                "performance": result
            })

        except Exception as e:
            print(f"Error running strategy: {strat}")
            print(e)

    ranked = sorted(
        results,
        key=lambda x: x["performance"].get("sharpe", 0),
        reverse=True
    )

    # ✅ SAVE AFTER RESULTS EXIST
    save_results(ranked)

    return ranked

if __name__ == "__main__":
    top = run_discovery(10)

    for i, strat in enumerate(top[:5]):
        print(f"\nRank {i+1}")
        print(strat)