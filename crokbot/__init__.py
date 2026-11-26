"""CrokBotTrading — a 24/7 AI trading desk.

Architecture (from @0xKiyoro's "Grok Bot + Jev" desk):

    code computes state  ->  Jev answers the battery  ->  code applies policy
         ->  risk engine checks (deterministic, no model)  ->  execution places order

- math/        computes mid price, spread, imbalance, realized vol (NO model arithmetic)
- jev/         judgment battery over the computed state (Choice/Score/Noul-shaped
               questions answered over the local Omniroute -> openrouter/typesafe/jev-router)
- policy/      composes Jev answers into intents; thresholds & weights live in code
- risk/        hard-coded deterministic gate, runs before every order, model has no vote
- execution/   Broker protocol + PaperBroker (simulator) + EToroBroker (stub until creds)
- desk/        the "Grok Bot" orchestrator running three bots (MarketMaker, House, Directional)
"""

__version__ = "0.1.0"