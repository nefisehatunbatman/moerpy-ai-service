"""Bounded provider calls with safe errors and usage telemetry."""
import json
import logging
import time
import httpx
from app.core.config import get_settings
logger=logging.getLogger(__name__)

class ProviderError(RuntimeError): pass
class ProviderRateLimitError(ProviderError): pass
class ProviderTimeoutError(ProviderError): pass

def post_json(url,key,payload):
    deadline=time.monotonic()+get_settings().llm_timeout_seconds
    last=None
    for attempt in range(3):
        remaining=deadline-time.monotonic()
        if remaining<=0: break
        try:
            response=httpx.post(url,headers={'Authorization':f'Bearer {key}'},json=payload,timeout=remaining)
            if response.status_code >= 400:
                logger.warning('provider_http_error', extra={'status': response.status_code, 'attempt': attempt+1})
            if response.status_code in (429,502,503,504):
                last=(ProviderRateLimitError if response.status_code == 429 else ProviderError)('Provider temporarily unavailable')
                retry_after = response.headers.get('retry-after', '')
                if retry_after.isdigit():
                    delay = int(retry_after)
                    if delay >= deadline-time.monotonic():
                        break
                    time.sleep(delay)
            else:
                response.raise_for_status()
                result=response.json()
                if not isinstance(result,dict): raise ValueError('Expected a JSON object')
                usage=result.get('usage',{})
                choices = result.get('choices')
                finish = choices[0].get('finish_reason') if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
                if finish in ('stop', 'length', 'content_filter'):
                    logger.info('model_finish', extra={'model': payload.get('model'), 'finish_reason': finish})
                safe_usage={k:usage[k] for k in ('prompt_tokens','completion_tokens','total_tokens') if isinstance(usage,dict) and isinstance(usage.get(k),int)}
                logger.info('model_usage',extra={'model':payload.get('model'),'usage':safe_usage,'attempt':attempt+1})
                return result
        except (httpx.TimeoutException,httpx.ConnectError) as exc:
            last=exc
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
            raise ProviderError('Provider response rejected') from exc
        if attempt<2:
            time.sleep(max(0,min(0.25*(2**attempt),deadline-time.monotonic())))
    error = ProviderRateLimitError if isinstance(last, ProviderRateLimitError) else ProviderTimeoutError if isinstance(last, httpx.TimeoutException) else ProviderError
    raise error('Provider retry/time budget exhausted') from last
