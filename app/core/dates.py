from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def reporting_today():
    return datetime.now(ZoneInfo(get_settings().reporting_timezone)).date()
