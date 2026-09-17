"""LLM client abstraction.

FakeLLMClient is selected by LLM_MODE=offline: it returns a generic
financial review request, without copying historical actions or claiming
to select tailored advice. No network call or numerical forecast is made.
It exists so the rest of the pipeline
(and CI) never requires a live API key, and so every layer downstream of
"the LLM" (grounding checks, confidence engine, decision lifecycle) can be
exercised for real.

OpenAICompatibleLLMClient talks to any OpenAI-compatible chat/completions
endpoint only when LLM_MODE=live is explicitly selected.
"""

import json
from abc import ABC, abstractmethod

from app.core.config import get_settings


class LLMClient(ABC):
    generator_name: str

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> dict: ...


class FakeLLMClient(LLMClient):
    """Offline contract fixture, never evidence of live pilot acceptance."""
    generator_name = 'fake_deterministic'

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        payload = json.loads(user_prompt.split("\n\n", 1)[1])
        evidence = payload['verified_evidence']
        reference = payload['reference_control']
        en = evidence.get('language') == 'en'
        text = 'Verified evidence requires a scoped control.' if en else 'Doğrulanmış kanıt kapsamı belirli bir kontrol gerektiriyor.'
        return dict(title=text, summary=text, problem_signal=text, recommended_decision=text,
                    reasoning=[text], decision_type=reference['decision_type'],
                    action_id=reference['action_id'], expected_impact=[], department='finance',
                    support_departments=evidence['support_departments'])

class OpenAICompatibleLLMClient(LLMClient):
    generator_name = "live_llm"

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.model_version = model

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        from app.llm.transport import post_json,ProviderError
        response=post_json(f'{self._base_url}/chat/completions',self._api_key,{
            'model':self._model,'messages':[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}],
            'response_format':{'type':'json_object'},'temperature':0.4,'max_tokens':get_settings().llm_max_tokens})
        try:
            choice = response['choices'][0]
            if choice.get('finish_reason') not in (None, 'stop'):
                raise ProviderError('Model output was incomplete')
            return json.loads(response['choices'][0]['message']['content'])
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            raise ProviderError('Model returned malformed structured output') from exc


def get_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_mode=='live':
        return OpenAICompatibleLLMClient(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model
        )
    return FakeLLMClient()
