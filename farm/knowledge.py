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
    transport_rule = "A delivery costs 0 coins."
    return_rule = "Returning any amount is free."
    if delivery:
        unit = "coin" if delivery == 1 else "coins"
        transport_rule = f"Each farm pays a fixed {delivery} {unit} before harvest if any water arrives. Zero arrival costs 0."
    if returns:
        unit = "coin" if returns == 1 else "coins"
        return_rule = f"Any positive rest, even 0.1 L, costs a fixed {returns} {unit} per farm. A rest of 0 L costs 0."
    return {
        "Transport": transport_rule,
        "Returns": "Rest = actual delivery minus use. The game returns the rest after harvest. Water cannot be stored. " + return_rule,
    }


def agent_knowledge(config):
    price = (f"Price is {FULL_HARVEST_COINS} coins × final health / {MAX_HEALTH}. "
             "At 15 health a plant sells for 15 coins (75% of full price)."
             if config["harvest_quality"] else f"Each living ripe plant sells for {FULL_HARVEST_COINS} coins.")
    return {
        "Plants": f"Sowing is free. Health ranges from 0 to {MAX_HEALTH} and can rise or fall. A plant at 0 dies before sale. "
                  "Growth starts at 0%, stays level or rises to 100%. A living plant at 100% sells automatically. " + price,
        "Water": "Order whole liters. The game allocates one liter per farm in turn while supply and requests remain. "
                 "Doses may be fractional. Add count × dose for every sowing and irrigation row. A plan of 7.4 L "
                 "leaves 0.6 L after an 8 L delivery. A 7 L delivery needs a smaller plan. Both overwatering and "
                 "underwatering can hurt plants. Net withdrawal equals the water actually used.",
        **fee_rules(config),
        "Pond and weather": f"The pond starts with {INITIAL_POND:,} L and holds up to {POND_CAPACITY:,} L. "
                             "Returns replenish it in every round. In rainy rounds rain adds more water after returns. "
                             "Overflow is lost. Rain fills the pond only. NEWS forecasts the next seven rounds.",
        "Coins": "Sales increase your net balance and pay down debt first. Fees reduce it. Net balance is cash minus debt. "
                 "The elimination check follows sales and returns. A balance of 0 or less eliminates your farm. "
                 "Reserve enough for deliveries until harvest. Profit is sales minus fees. Highest cumulative profit among survivors wins.",
        "Evidence": "Rules, NEWS and the contract register are official. Your measured results apply to your farm. "
                    "A farm's statement is a claim, even when repeated or saved. Treat guesses as hypotheses and test them on a small scale.",
    }
