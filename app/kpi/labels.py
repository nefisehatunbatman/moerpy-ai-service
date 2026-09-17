"""Turkish display labels for metric keys. Presentation only — never used
in calculation logic. Falls back to the raw metric key if missing.
"""

METRIC_LABELS_TR: dict[str, str] = {
    "revenue": "Gelir",
    "cogs": "Satılan Malın Maliyeti",
    "gross_profit": "Brüt Kâr",
    "gross_margin_pct": "Brüt Kâr Marjı",
    "branch_margin_gap_pct": "Şubeler Arası Marj Farkı",
    "branch_margin_gap_try": "Şubeler Arası Marj Farkının Parasal Karşılığı",
    "unit_cost_variance_pct": "Birim Maliyet Sapması",
    "unit_cost_variance_try": "Birim Maliyet Sapmasının Parasal Karşılığı",
    "inventory_value": "Envanter Değeri",
    "days_inventory_outstanding": "Envanterin Nakde Dönüşüm Süresi",
    "working_capital_in_inventory_pct": "Envanterde Kilitlenen İşletme Sermayesi Oranı",
    "waste_to_revenue_pct": "İsrafın Gelire Oranı",
    "waste_value_try": "İsrafın Parasal Karşılığı",
}


METRIC_LABELS_EN={
    'revenue':'Revenue','cogs':'Cost of Goods Sold','gross_profit':'Gross Profit','gross_margin_pct':'Gross Margin',
    'branch_margin_gap_pct':'Branch Margin Gap','branch_margin_gap_try':'Branch Margin Gap Scenario Value',
    'unit_cost_variance_pct':'Unit Cost Variance','unit_cost_variance_try':'Unit Cost Variance Value',
    'inventory_value':'Inventory Value','days_inventory_outstanding':'Inventory Days (Ending Stock Proxy)',
    'working_capital_in_inventory_pct':'Inventory to Revenue Ratio','waste_to_revenue_pct':'Waste to Revenue Ratio','waste_value_try':'Waste Value'}

def label_for(metric: str,language='tr') -> str:
    if language=='en': return METRIC_LABELS_EN.get(metric,METRIC_LABELS_TR.get(metric,metric))
    return METRIC_LABELS_TR.get(metric, metric)
