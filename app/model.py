from pydantic import BaseModel, Field
from typing import List, Optional

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: Optional[str] = None
    tts: bool = False
    imgbase64: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str

class ChatHistory(BaseModel):
    session_id: str
    messages: List[ChatMessage]

class JarvisActions(BaseModel):
    wopens: List[str] = []
    plays: List[str] = []
    images: List[str] = []
    contents: List[str] = []
    googlesearches: List[str] = []
    youtubesearches: List[str] = []
    cam: Optional[dict] = None

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)