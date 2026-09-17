"""Fixed financial decision taxonomy (spec section 3). Every decision must
carry exactly one of these — the LLM never invents a new one, and any
value it emits outside this set is rejected.
"""

DECISION_TYPES = {
    "COST_OPTIMIZATION",
    "BUDGET_REALLOCATION",
    "MARGIN_PROTECTION",
    "PRICING",
    "WORKING_CAPITAL",
    "CASH_FLOW",
    "PROCUREMENT_FINANCE",
    "INVENTORY_FINANCE",
    "CAPEX",
    "OPEX",
    "REVENUE_OPTIMIZATION",
    "PROFITABILITY",
    "FINANCIAL_RISK",
}
