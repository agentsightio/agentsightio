from typing import Dict, Union, BinaryIO
from io import BytesIO

FileData = Union[bytes, BinaryIO, BytesIO]

# Updated attachment input type
AttachmentInput = Union[
    Dict[str, str],  # For base64 mode: {'filename': str, 'mime_type': str, 'data': str}
    Dict[str, Union[str, FileData]]  # For form_data mode: {'filename': str, 'mime_type': str, 'data': FileData}
]

class TokenHandler:
    def __init__(self):
        self.prompt_llm_token_count = 0
        self.completion_llm_token_count = 0
        self.total_llm_token_count = 0
        self.total_embedding_token_count = 0
