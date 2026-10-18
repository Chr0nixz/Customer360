class C360Error(Exception):
    """Safe reason codes are public; underlying database errors stay private."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class QueryRejected(C360Error):
    pass


class ExecutionFailure(C360Error):
    pass
