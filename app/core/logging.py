import logging
import sys
import json
import traceback

from app.core.config import get_settings

_SENSITIVE_KEYS = {"llm_api_key", "embedding_api_key", "api_key", "authorization", "token"}


def configure_logging() -> None:
    settings = get_settings()
    handler=logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=getattr(logging,settings.ai_service_log_level.upper(),logging.INFO),handlers=[handler],force=True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def safe_extra(**fields: object) -> dict:
    """Drop anything that looks like a secret before it reaches a log line."""
    return {k: v for k, v in fields.items() if k.lower() not in _SENSITIVE_KEYS}

class JsonFormatter(logging.Formatter):
    def format(self,record):
        payload={'time':self.formatTime(record),'level':record.levelname,'event':record.getMessage(),'logger':record.name}
        # Allowlist: headers, prompts, evidence, credentials and exception payloads are never serialized.
        for key in ('request_id','decision_id','company_id','anomaly_id','entry_id','status','duration_seconds','error_type','model','usage','attempt','finish_reason'):
            if hasattr(record,key): payload[key]=getattr(record,key)
        if record.exc_info:
            # Omit messages, source text and locals: they may contain secrets.
            payload['traceback'] = [dict(file=f.filename, line=f.lineno, function=f.name)
                                    for f in traceback.extract_tb(record.exc_info[2])]
        return json.dumps(payload,ensure_ascii=False,default=str)
