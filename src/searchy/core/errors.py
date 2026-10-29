class SearchyError(Exception):
    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class InvalidInput(SearchyError):
    def __init__(self, message: str):
        super().__init__(message, 422)
