"""Public game rules shared by the model, the setup preview and the farm inspector."""

MAX_HEALTH = 20
FULL_HARVEST_COINS = 20
POND_CAPACITY = 50_000
INITIAL_POND = 5_000


def return_cost(config):
    # Recorded games before configurable fees charged 40 coins for returns.
    return config.get("return_fee_coins", 40) if config.get("return_fee_enabled", True) else 0


def fee_report(config):
    return (f"Each farm pays {config['delivery_fee_coins']} coins for a positive delivery and "
            f"{return_cost(config)} coins for a positive return. These rates are fixed. "
            "Receiving or returning zero water incurs no corresponding charge.")


def fee_rules(config):
    delivery = config["delivery_fee_coins"]
    returns = return_cost(config)
    transport_rule = "Water delivery is free."
    return_rule = "Returning any amount is free."
    if delivery:
        unit = "coin" if delivery == 1 else "coins"
        transport_rule = f"Any positive delivery costs a fixed {delivery} {unit} per farm before harvest. A zero delivery costs nothing."
    if returns:
        unit = "coin" if returns == 1 else "coins"
        return_rule = f"Any positive return costs a fixed {returns} {unit} per farm. Exact use avoids this fee."
    return {
        "Transport": transport_rule,
        "Returns": "Unused water returns to the pond after harvest and becomes available next round. " + return_rule,
    }


def agent_knowledge(config):
    price = (f"Price is {FULL_HARVEST_COINS} coins × final health / {MAX_HEALTH}. "
             "At 15 health a plant sells for 15 coins (75% of full price)."
             if config["harvest_quality"] else f"Each living ripe plant sells for {FULL_HARVEST_COINS} coins.")
    return {
        "Plants": f"Planting is free. Health can rise or fall within 0–{MAX_HEALTH}. At each growth check, 0 health means death "
                  "and no sale, even at maturity. Growth starts at 0%, can stall or increase, and never falls. "
                  "At 100% a surviving plant sells automatically and leaves your farm. " + price,
        "Water": "Order whole liters for this round. Farms take turns receiving one liter until demand or "
                 "supply runs out. Plan for existing plants and seedlings using count × liters per plant. "
                 "Ten plants at 3 L each need 30 L. Use the actual delivery. Both excess and insufficient "
                 "watering can harm plants. Net withdrawal is delivery minus returns.",
        **fee_rules(config),
        "Pond and weather": f"The shared pond starts at {INITIAL_POND:,} L and holds {POND_CAPACITY:,} L. "
                            "Dry and rainy spells alternate. In dry rounds only returns refill the pond. "
                            "In rainy rounds rain adds water after returns. Overflow is lost. "
                            "Rain never irrigates plants. Use the seven-day forecast to plan for scarcity.",
        "Coins": "Net balance = cash minus debt. Starting capital is your reserve. Sales pay down debt "
                 "and raise your balance. Fees lower it. A delivery can put you below zero before harvest. "
                 "After sales and returns each round, a net balance of 0 or less eliminates your farm, "
                 "even without a harvest. A larger reserve covers more rounds of fees until harvest. Avoid unnecessary expenses. "
                 "Profit is sales minus fees. Highest cumulative profit among surviving farms wins.",
    }
