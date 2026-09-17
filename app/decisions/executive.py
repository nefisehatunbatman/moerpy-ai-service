"""Auditable executive controls. These are pilot controls, not company mandates.

The model selects a permitted control; code renders its scope and numeric facts.
No rule here authorizes purchase freezes, price changes or savings forecasts.
"""
import hashlib
from dataclasses import dataclass

from app.evidence.models import EvidencePackage

VERSION = 'executive-controls-v1'


@dataclass(frozen=True)
class Control:
    category: str
    action_tr: str
    action_en: str
    risk_tr: str
    risk_en: str


CONTROLS = {
    'waste_to_revenue_pct': Control('PROFITABILITY',
        'Operasyon ve finans ekiplerini israf kayıtlarını ürün ve neden bazında uzlaştırmak, önlenebilir kayıplar için sorumlusu belirlenmiş düzeltici plan hazırlamak ve planı yönetim onayına sunmakla görevlendirin.',
        'Assign operations and finance to reconcile waste records by product and cause, prepare an owned corrective plan for preventable losses, and submit it for management approval.',
        'Kaynak doğrulanmadan sipariş azaltılması ürün bulunurluğunu düşürebilir.',
        'Reducing orders before verifying the cause could reduce product availability.'),
    'unit_cost_variance_pct': Control('COST_OPTIMIZATION',
        'Satın alma ve finans ekiplerini gerçekleşen maliyet ile onaylı bütçe farkını uzlaştırmak ve doğrulanan fark için sözleşme müzakeresi planını yönetim onayına sunmakla görevlendirin.',
        'Assign procurement and finance to reconcile actual costs against the approved budget and submit a contract negotiation plan for the verified variance.',
        'Maliyet farkını yalnız tedarikçiye bağlamak yanlış tedarikçi değişikliğine yol açabilir.',
        'Attributing the whole variance to suppliers could lead to an inappropriate supplier change.'),
    'gross_margin_pct': Control('PROFITABILITY',
        'Finans ve operasyon ekiplerini ürün karması ve maliyet kayıtlarını uzlaştırmak, marj farkını açıklayan fiyat ve maliyet senaryolarını yönetim onayına sunmakla görevlendirin.',
        'Assign finance and operations to reconcile product mix and cost records and submit pricing and cost scenarios explaining the margin gap for management approval.',
        'Talep esnekliği bilinmeden fiyat artışı satış kaybına yol açabilir.',
        'Price increases without demand elasticity evidence could reduce sales.'),
    'branch_margin_gap_pct': Control('PROFITABILITY',
        'Finans ekibini şubelerin ürün karması ve maliyet kapsamını uzlaştırmak ve karşılaştırılabilir şubeler için kârlılık iyileştirme planını yönetim onayına sunmakla görevlendirin.',
        'Assign finance to reconcile branch product mix and cost coverage and submit a profitability plan for comparable branches for management approval.',
        'Ürün karması farklı şubeler arasında kaynak aktarımı hizmet seviyesini bozabilir.',
        'Moving resources between branches with different product mixes could harm service levels.'),
    'days_inventory_outstanding': Control('WORKING_CAPITAL',
        'Operasyon ve finans ekiplerini stok yaşlandırma ile talep ve hizmet seviyesi kısıtlarını eşleştirmek, sipariş erteleme adaylarını yönetim onayına sunmakla görevlendirin.',
        'Assign operations and finance to reconcile inventory ageing with demand and service constraints and submit candidate order deferrals for management approval.',
        'Dönem sonu stok oranı tek başına yavaş dönen ürünü belirlemez; sipariş kesintisi stok tükenmesine yol açabilir.',
        'An ending-stock ratio alone does not identify slow-moving items; cutting orders could cause stockouts.'),
    'working_capital_in_inventory_pct': Control('CASH_FLOW',
        'Finans ve satın alma ekiplerini stok değerini açık siparişler ve ödeme takvimiyle eşleştirmek, ertelenebilir nakit taahhütlerini yönetim onayına sunmakla görevlendirin.',
        'Assign finance and procurement to reconcile inventory value with open orders and payment schedules and submit deferrable cash commitments for management approval.',
        'Stok değeri önlenebilir nakit çıkışı değildir; sözleşme kontrolü olmadan erteleme ceza doğurabilir.',
        'Inventory value is not avoidable cash outflow; deferrals without contract checks could incur penalties.'),
}


def control_for(evidence):
    if evidence.assessment_status != 'context_available' or evidence.completeness_status != 'complete':
        return None
    if not evidence.signals or len(evidence.thresholds) != 1:
        return None
    if evidence.thresholds[0].metric != evidence.signals[0].metric:
        return None
    return CONTROLS.get(evidence.signals[0].metric)


def project(evidence: EvidencePackage) -> dict:
    """Every number rendered here is copied from the saved evidence snapshot."""
    en = evidence.language == 'en'
    own = evidence.signals[0] if evidence.signals else None
    control = control_for(evidence)
    refs = [f'signal:{i}' for i, _ in enumerate(evidence.signals)]
    digest = hashlib.sha256(evidence.model_dump_json(exclude={'confidence_reasons'}).encode()).hexdigest()
    finding = (f'{evidence.entity_id}: {own.label} = {own.value:g} {own.unit}.' if own else
               ('Verified primary signal missing.' if en else 'Doğrulanmış ana gösterge eksik.'))
    thresholds = [t for t in evidence.thresholds if own and t.metric == own.metric]
    rationale = [finding]
    if thresholds:
        t = thresholds[0]
        rationale.append((f'Alert boundaries: warning {t.warning_value:g}, critical {t.critical_value:g} {own.unit} ({t.operator}).' if en else
                          f'Alarm sınırları: uyarı {t.warning_value:g}, kritik {t.critical_value:g} {own.unit} ({t.operator}).'))
    rationale.append('The cause has not been verified.' if en else 'Neden henüz doğrulanmamıştır.')
    impact_reason = ('Avoidable share, implementation cost and timing are missing; reliable savings cannot be calculated.' if en else
                     'Önlenebilir pay, uygulama maliyeti ve zamanlama eksik; güvenilir tasarruf hesaplanamıyor.')
    trace = dict(evidence_id='EVD-'+digest, anomaly_id=evidence.anomaly_id, run_id=evidence.run_id,
                 tenant_id=evidence.tenant_id, company_id=evidence.company_id,
                 period=evidence.period.model_dump(), calculation_source='app/kpi/calculation.py',
                 policy_version=VERSION, evidence_policy=evidence.evidence_policy.model_dump(mode='json') if evidence.evidence_policy else None,
                 signals=[dict(ref=ref, **s.model_dump()) for ref, s in zip(refs, evidence.signals)],
                 source_refs_are_sampled=any(s.source_count > len(s.source_ids) for s in evidence.signals))
    trace['numeric_claims'] = [dict(ref=ref, source_type='DETERMINISTIC_METRIC',
        value=s.value, unit=s.unit, formula=s.formula, source_digest=s.source_digest)
        for ref, s in zip(refs, evidence.signals)]
    trace['numeric_claims'] += [dict(ref=f'threshold:{i}', source_type='COMPANY_THRESHOLD',
        approval_status='not_established', **t.model_dump()) for i, t in enumerate(thresholds)]
    trace['period_status'] = 'closure_not_verified'
    trace['semantic_limits'] = ['revenue_is_not_collected_cash', 'ending_stock_is_not_average_stock',
        'no_seasonality_or_promotion_adjustment', 'causation_not_verified', 'threshold_is_not_success_target']
    blockers = list(evidence.information_gaps) if not control else []
    if not control:
        blockers.append('supported_control_unavailable')
    action = (control.action_en if en else control.action_tr) if control else (
        'Decision blocked. Supply verified evidence and an approved action policy.' if en else
        'Karar bloke edildi. Doğrulanmış kanıt ve onaylı aksiyon kuralı sağlayın.')
    risks = ([control.risk_en if en else control.risk_tr] if control else [])
    conditions = [
        'No pricing, purchase freeze or supplier change is authorized by this control.' if en else
        'Bu görev ataması fiyat değişikliği, satın alma durdurma veya tedarikçi değişikliği yetkisi vermez.',
        'Obtain company approval for scope, resources and the resulting operational plan.' if en else
        'Kapsam, kaynak ve hazırlanacak operasyon planı için şirket onayı alın.',
    ]
    success = dict(metric=own.metric if own else None, baseline=own.value if own else None,
                   unit=own.unit if own else None, target=None, deadline=None,
                   target_status='company_target_and_deadline_missing',
                   completion=('Reconciled evidence and an owned plan submitted for approval.' if en else
                               'Uzlaştırılmış kayıtlar ve sorumlusu belirlenmiş planın onaya sunulması.'),
                   evidence_refs=refs[:1])
    return dict(title=f'{own.label}: {own.value:g} {own.unit} — {evidence.entity_id}' if own else finding,
                summary=finding, problem_signal=finding, recommended_decision=f'{evidence.entity_id}: {action}',
                decision_type=control.category if control else 'FINANCIAL_RISK', reasoning=rationale,
                expected_impact=[],
                decision_readiness='control_plan_only' if control else 'blocked',
                action_id=own.metric+'/control-plan' if control else None,
                action_policy_source='PILOT_CONTROL_NOT_COMPANY_POLICY', blockers=sorted(set(blockers)),
                risks=risks, do_not_apply_when=conditions, success_metric=success,
                impact_assessment=dict(status='unavailable', explanation=impact_reason,
                    quantified_context=evidence.quantified_impact.model_dump() if evidence.quantified_impact else None),
                traceability=trace)
