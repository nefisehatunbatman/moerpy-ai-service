from datetime import date

import pytest

from app.anomaly.detector import detect_anomalies
from app.data.models import Period
from app.data.providers.fake_provider import FakeERPDataProvider
from app.evidence.builder import build_evidence
from app.financial_impact.analyzer import analyze
from app.kpi.engine import compute_kpis
from app.llm.client import FakeLLMClient, LLMClient
from app.llm.decision_generator import (
    NumberGroundingError,
    enforce_taxonomy_and_department,
    generate_decision,
    verify_number_grounding,
)
from app.rag.embeddings import LocalHashEmbedding
from app.rag.knowledge_base import KnowledgeBaseRepository
from app.rag.retriever import retrieve
from app.thresholds.defaults import get_seed_thresholds
from app.thresholds.repository import ThresholdRepository

FEB = Period(start=date(2026, 2, 1), end=date(2026, 2, 28))


def _evidence_and_retrieved(metric, company_id, db_session):
    repo = ThresholdRepository(db_session)
    repo.seed_if_empty(company_id, get_seed_thresholds(company_id))
    thresholds = repo.list_for_company(company_id)
    kpis = compute_kpis(FakeERPDataProvider(), company_id, FEB)
    anomalies = detect_anomalies(company_id, FEB, kpis, thresholds)
    anomaly = next(a for a in anomalies if a.metric == metric)
    impact = analyze(anomaly, kpis)
    evidence = build_evidence(anomaly, impact, kpis, thresholds)

    kb = KnowledgeBaseRepository(db_session, LocalHashEmbedding())
    kb.seed_if_empty()
    retrieved = retrieve(kb, evidence, top_k=3)
    return evidence, retrieved


def test_fake_llm_client_end_to_end(db_session):
    evidence, retrieved = _evidence_and_retrieved("working_capital_in_inventory_pct", "COMP-001", db_session)
    output = generate_decision(evidence, retrieved, FakeLLMClient())

    assert output.decision_type == "CASH_FLOW"
    assert output.department == "finance"
    assert len(output.reasoning) >= 1
    assert output.expected_impact == []
    assert evidence.quantified_impact.value == 492000


class _LyingDecisionTypeClient(LLMClient):
    generator_name = "test_lying"

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        return {
            "title": "Yanlış Karar Türü Testi",
            "summary": "Bu özet doğrulanmış hiçbir sayı içermiyor.",
            "decision_type": "PRICING",  # a valid taxonomy value, different from the reference_control's CASH_FLOW
            "problem_signal": "Envanterde nakit kilitlenmesi gözlemlendi.",
            "recommended_decision": "Sermaye tahsisi kararları gözden geçirilmelidir.",
            "reasoning": ["Envanter seviyesi gelire kıyasla yüksek."],
            "expected_impact": [{"metric": "cash_flow", "direction": "increase", "type": "qualitative"}],
            "department": "operations",  # deliberately wrong — must always be finance
            "support_departments": ["operations", "marketing"],  # marketing isn't in evidence
        }


def test_model_chooses_its_own_decision_type_but_not_department(db_session):
    evidence, retrieved = _evidence_and_retrieved("working_capital_in_inventory_pct", "COMP-001", db_session)
    output = generate_decision(evidence, retrieved, _LyingDecisionTypeClient())

    assert output.decision_type == "PRICING"  # the model's own categorization is now authored, not overridden
    assert output.department == "finance"  # still forced back to finance — an org invariant, not a narrative choice
    assert "marketing" not in output.support_departments  # not in evidence, filtered out
    assert "operations" in output.support_departments


class _HallucinatingNumberClient(LLMClient):
    generator_name = "test_hallucinating"

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        return {
            "title": "Envanter Maliyeti Azaltımı",
            "summary": "Bu kararla birlikte maliyetlerin %37 azalması beklenmektedir.",  # invented number
            "decision_type": "CASH_FLOW",
            "problem_signal": "Envanterde nakit kilitlenmesi gözlemlendi.",
            "recommended_decision": "Sermaye tahsisi kararları gözden geçirilmelidir.",
            "reasoning": ["Envanter seviyesi gelire kıyasla yüksek."],
            "expected_impact": [
                {"metric": "working_capital_in_inventory_pct", "direction": "decrease", "type": "qualitative"}
            ],
            "department": "finance",
            "support_departments": ["operations"],
        }


def test_hallucinated_percentage_in_free_text_is_rejected(db_session):
    evidence, retrieved = _evidence_and_retrieved("working_capital_in_inventory_pct", "COMP-001", db_session)
    with pytest.raises(NumberGroundingError):
        generate_decision(evidence, retrieved, _HallucinatingNumberClient())


class _InventedQuantitativeImpactClient(LLMClient):
    generator_name = "test_invented_quant"

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        return {
            "title": "Envanter Maliyeti Azaltımı",
            "summary": "Doğrulanmış sinyallere dayalı bir özet.",
            "decision_type": "CASH_FLOW",
            "problem_signal": "Envanterde nakit kilitlenmesi gözlemlendi.",
            "recommended_decision": "Sermaye tahsisi kararları gözden geçirilmelidir.",
            "reasoning": ["Envanter seviyesi gelire kıyasla yüksek."],
            "expected_impact": [
                {
                    "metric": "working_capital_in_inventory_pct",
                    "direction": "decrease",
                    "type": "quantitative",
                    "value": 999999,  # not grounded anywhere in evidence
                    "unit": "TRY",
                }
            ],
            "department": "finance",
            "support_departments": ["operations"],
        }


def test_invented_quantitative_impact_value_is_downgraded_to_qualitative(db_session):
    evidence, retrieved = _evidence_and_retrieved("working_capital_in_inventory_pct", "COMP-001", db_session)
    output = generate_decision(evidence, retrieved, _InventedQuantitativeImpactClient())

    # The invented 999999 TRY value is stripped; direction survives as qualitative only.
    assert len(output.expected_impact) == 1
    assert output.expected_impact[0].type == "qualitative"
    assert output.expected_impact[0].value is None and output.expected_impact[0].unit is None
    assert output.expected_impact[0].metric == "working_capital_in_inventory_pct"


def test_numeric_narrative_is_rejected_even_if_number_exists(db_session):
    evidence, retrieved = _evidence_and_retrieved("unit_cost_variance_pct", "COMP-001", db_session)

    class HonestClient(LLMClient):
        generator_name = "test_honest"

        def generate(self, system_prompt: str, user_prompt: str) -> dict:
            variance = next(s.value for s in evidence.signals if s.metric == "unit_cost_variance_pct")
            return {
                "title": "Birim Maliyet Sapmasının Yönetimi",
                "summary": f"Birim maliyet sapması %{variance} seviyesinde gerçekleşti.",
                "decision_type": "COST_OPTIMIZATION",
                "problem_signal": "Birim maliyet sapması eşik değerin üzerinde.",
                "recommended_decision": "Tedarik bütçesi yeniden değerlendirilmelidir.",
                "reasoning": ["Gerçekleşen maliyet standart maliyetin üzerinde."],
                "expected_impact": [
                    {"metric": "unit_cost_variance_pct", "direction": "decrease", "type": "qualitative"}
                ],
                "department": "finance",
                "support_departments": ["procurement"],
            }

    with pytest.raises(NumberGroundingError):
        generate_decision(evidence, retrieved, HonestClient())

