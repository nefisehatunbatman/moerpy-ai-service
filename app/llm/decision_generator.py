"""The model writes qualitative advice; all quantitative facts are rendered by code."""
import re
import unicodedata
from app.evidence.models import EvidencePackage
from app.llm.client import LLMClient
from app.llm.prompts import SYSTEM_PROMPT,build_user_prompt
from app.llm.schemas import ExpectedImpactItem,LLMDecisionOutput
from app.rag.retriever import RetrievedDecision

class NumberGroundingError(Exception): pass
class LLMOutputValidationError(Exception): pass

_QUANTITY_COMMON=re.compile(r'\d|[%₺$€]')
# Checked together (code-switched numeric words should still be caught either way), except
# "on" is dropped from the Turkish list when validating English text: it's the Turkish word for
# ten, but also an ordinary English preposition ("clarity on the extent...") — keeping it in the
# shared list rejected perfectly clean English narrative every time the model used that word.
_NUMBER_WORDS_TR=re.compile(r'\b(?:yüzde|yuzde|milyon|milyar|bin|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|elli|yüz|sıfır|sifir|altmış|yetmiş|seksen|doksan|yarı|yarıya)\b',re.IGNORECASE)
_NUMBER_WORDS_TR_IN_EN_TEXT=re.compile(r'\b(?:yüzde|yuzde|milyon|milyar|bin|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|yirmi|otuz|kırk|elli|yüz|sıfır|sifir|altmış|yetmiş|seksen|doksan|yarı|yarıya)\b',re.IGNORECASE)
_NUMBER_WORDS_EN=re.compile(r'\b(?:percent|million|billion|hundred|thousand|two|three|four|five|six|seven|eight|nine|ten|zero|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|half|double|twice)\b',re.IGNORECASE)

def verify_number_grounding(output:LLMDecisionOutput,evidence:EvidencePackage)->LLMDecisionOutput:
    tr_words = _NUMBER_WORDS_TR_IN_EN_TEXT if evidence.language=='en' else _NUMBER_WORDS_TR
    for text in [output.title,output.summary,output.problem_signal,output.recommended_decision,*output.reasoning]:
        normalized = unicodedata.normalize('NFKC', text)
        if (_QUANTITY_COMMON.search(normalized) or any(ch.isnumeric() for ch in normalized)
                or tr_words.search(normalized) or _NUMBER_WORDS_EN.search(normalized)):
            raise NumberGroundingError('Numeric narrative is not allowed; use deterministic evidence fields')
    if not evidence.signals:
        raise NumberGroundingError('Insufficient evidence')
    metrics = {s.metric for s in evidence.signals if s.scope_relation == 'same_entity'}
    impacts = [] if evidence.assessment_status == 'review_required' else [
        ExpectedImpactItem(metric=i.metric, direction=i.direction, type='qualitative')
        for i in output.expected_impact if i.metric in metrics
    ]
    return output.model_copy(update={'expected_impact':impacts})

def enforce_taxonomy_and_department(output,evidence):
    if evidence.assessment_status == 'review_required':
        english = evidence.language == 'en'
        output = output.model_copy(update={
            'title': 'Financial review required' if english else 'Finansal inceleme gerekli',
            'decision_type': 'FINANCIAL_RISK', 'expected_impact': [],
            'recommended_decision': (
                'Assess financial relevance with the finance team; establish missing context before choosing an action.'
                if english else 'Finansal anlamı finans ekibiyle değerlendirin; aksiyon seçmeden önce eksik bağlamı tamamlayın.'),
            'reasoning': [
                'Financial context is insufficient; causes and monetary effects have not been established.'
                if english else 'Finansal bağlam yetersizdir; nedenler ve parasal etkiler doğrulanmamıştır.'
            ],
        })
    return output.model_copy(update={'department':'finance',
        'support_departments':list(evidence.support_departments)})

_RETRY_REMINDER = (
    "\n\nYour previous response was rejected: it contained a digit, percentage, currency amount, "
    "spelled-out quantity, or duration somewhere in the narrative. Write a new response from scratch "
    "with absolutely no numeric content anywhere in title, summary, problem_signal, recommended_decision, "
    "or reasoning — describe the situation and the action in words only."
)

def generate_decision(evidence:EvidencePackage,retrieved:list[RetrievedDecision],llm_client:LLMClient)->LLMDecisionOutput:
    if not evidence.signals: raise NumberGroundingError('Insufficient evidence')
    base_prompt=SYSTEM_PROMPT.replace('Write in Turkish.','Write in English.' if evidence.language=='en' else 'Write in Turkish.')
    user_prompt=build_user_prompt(evidence,retrieved)
    last_exc=None
    for attempt in (0,1):
        # One automatic retry with a stricter reminder if the model violates number-grounding
        # or returns an invalid schema — most real failures are transient model slips, not
        # evidence problems, so a single retry clears them without surfacing a 422 to the caller.
        prompt=base_prompt if attempt==0 else base_prompt+_RETRY_REMINDER
        raw=llm_client.generate(prompt,user_prompt)
        try:
            output=LLMDecisionOutput.model_validate(raw)
        except Exception as exc:
            last_exc=LLMOutputValidationError('Invalid structured narrative')
            last_exc.__cause__=exc
            continue
        try:
            output=verify_number_grounding(output,evidence)
        except NumberGroundingError as exc:
            last_exc=exc
            continue
        output=enforce_taxonomy_and_department(output,evidence)
        # The model authors title/summary/problem_signal/recommended_decision/decision_type/
        # reasoning itself now — no forced override from the executive control catalog.
        # Safety is enforced by what precedes this line (number grounding, taxonomy,
        # forced department) plus the separate, always-deterministic executive_contract
        # (risks/do_not_apply_when/success_metric/traceability) shown alongside the card
        # in app/decisions/service.py — not by overwriting the model's narrative.
        return output
    raise last_exc
