"""Error รูปแบบ OpenAI API สำหรับ endpoint /v1/*"""


class ApiError(Exception):
    def __init__(self, status: int, message: str, etype: str = "invalid_request_error"):
        self.status = status
        self.message = message
        self.etype = etype
        super().__init__(message)
