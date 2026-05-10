class LoreError(Exception):
    pass


class NotFoundError(LoreError):
    pass


class ValidationError(LoreError):
    pass
