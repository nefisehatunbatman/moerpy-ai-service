"""Only explicit domain errors may become public client errors."""


class InvalidSourceDataError(ValueError):
    pass


class InvalidPeriodError(ValueError):
    pass


class CompanyNotFoundError(LookupError):
    pass
