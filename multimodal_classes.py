import base64
from pathlib import Path
from typing import Dict, Any

# 多模态输入类
class Text:
    def __init__(self, content: str):
        self.type = "text"
        self.content = content

    def to_dict(self):
        return {"text": self.content}

class Image:
    def __init__(self, path: str = None, url: str = None, base64: str = None, byte: bytes = None, mime_type: str = None):
        self.type = "image"
        self.source = {}
        self.url = url  # 保存 URL，延迟异步处理
        if path:
            self.source["base64"] = encode_file_to_base64(Path(path).read_bytes())
            self.source["mime_type"] = get_mime_type(path)
            self.source["filename"] = Path(path).name
        elif url:
            self.source["mime_type"] = mime_type or "image/jpeg"
            self.source["filename"] = url.split("/")[-1] or "downloaded_image"
        elif base64:
            self.source["base64"] = base64
            self.source["mime_type"] = mime_type or "image/jpeg"
            self.source["filename"] = "inline_image"
        elif byte:
            self.source["base64"] = encode_file_to_base64(byte)
            self.source["mime_type"] = mime_type or "image/jpeg"
            self.source["filename"] = "byte_image"

    async def to_dict(self):
        if self.url and "base64" not in self.source:
            data = await download_and_encode_file(self.url)
            self.source["base64"] = data["data"]
            self.source["mime_type"] = data["mime_type"]
        return {"inline_data": {"mime_type": self.source["mime_type"], "data": self.source["base64"]}}

class Audio:
    def __init__(self, path: str = None, url: str = None, base64: str = None, byte: bytes = None, mime_type: str = None):
        self.type = "audio"
        self.source = {}
        self.url = url
        if path:
            self.source["base64"] = encode_file_to_base64(Path(path).read_bytes())
            self.source["mime_type"] = get_mime_type(path)
            self.source["filename"] = Path(path).name
        elif url:
            self.source["mime_type"] = mime_type or "audio/mpeg"
            self.source["filename"] = url.split("/")[-1] or "downloaded_audio"
        elif base64:
            self.source["base64"] = base64
            self.source["mime_type"] = mime_type or "audio/mpeg"
            self.source["filename"] = "inline_audio"
        elif byte:
            self.source["base64"] = encode_file_to_base64(byte)
            self.source["mime_type"] = mime_type or "audio/mpeg"
            self.source["filename"] = "byte_audio"

    async def to_dict(self, upload: bool = False):
        if self.url and "base64" not in self.source:
            data = await download_and_encode_file(self.url)
            self.source["base64"] = data["data"]
            self.source["mime_type"] = data["mime_type"]
        if upload:
            file_uri = await upload_to_gemini_media(base64.b64decode(self.source["base64"]), self.source["mime_type"])
            return {"fileData": {"mimeType": self.source["mime_type"], "fileUri": file_uri}}
        return {"inline_data": {"mime_type": self.source["mime_type"], "data": self.source["base64"]}}

class Video:
    def __init__(self, path: str = None, url: str = None, base64: str = None, byte: bytes = None, mime_type: str = None):
        self.type = "video"
        self.source = {}
        self.url = url
        if path:
            self.source["base64"] = encode_file_to_base64(Path(path).read_bytes())
            self.source["mime_type"] = get_mime_type(path)
            self.source["filename"] = Path(path).name
        elif url:
            self.source["mime_type"] = mime_type or "video/mp4"
            self.source["filename"] = url.split("/")[-1] or "downloaded_video"
        elif base64:
            self.source["base64"] = base64
            self.source["mime_type"] = mime_type or "video/mp4"
            self.source["filename"] = "inline_video"
        elif byte:
            self.source["base64"] = encode_file_to_base64(byte)
            self.source["mime_type"] = mime_type or "video/mp4"
            self.source["filename"] = "byte_video"

    async def to_dict(self, upload: bool = False):
        if self.url and "base64" not in self.source:
            data = await download_and_encode_file(self.url)
            self.source["base64"] = data["data"]
            self.source["mime_type"] = data["mime_type"]
        if upload:
            file_uri = await upload_to_gemini_media(base64.b64decode(self.source["base64"]), self.source["mime_type"])
            return {"fileData": {"mimeType": self.source["mime_type"], "fileUri": file_uri}}
        return {"inline_data": {"mime_type": self.source["mime_type"], "data": self.source["base64"]}}

class CustomFile:
    def __init__(self, path: str = None, url: str = None, base64: str = None, byte: bytes = None, mime_type: str = None):
        self.type = "file"
        self.source = {}
        self.url = url
        if path:
            self.source["base64"] = encode_file_to_base64(Path(path).read_bytes())
            self.source["mime_type"] = get_mime_type(path)
            self.source["filename"] = Path(path).name
        elif url:
            self.source["mime_type"] = mime_type or "application/octet-stream"
            self.source["filename"] = url.split("/")[-1] or "downloaded_file"
        elif base64:
            self.source["base64"] = base64
            self.source["mime_type"] = mime_type or "application/octet-stream"
            self.source["filename"] = "inline_file"
        elif byte:
            self.source["base64"] = encode_file_to_base64(byte)
            self.source["mime_type"] = mime_type or "application/octet-stream"
            self.source["filename"] = "byte_file"

    async def to_dict(self, upload: bool = False):
        if self.url and "base64" not in self.source:
            data = await download_and_encode_file(self.url)
            self.source["base64"] = data["data"]
            self.source["mime_type"] = data["mime_type"]
        if upload and len(base64.b64decode(self.source["base64"])) > 20 * 1024 * 1024:
            file_uri = await upload_to_gemini_media(base64.b64decode(self.source["base64"]), self.source["mime_type"])
            return {"fileData": {"mimeType": self.source["mime_type"], "fileUri": file_uri}}
        return {"inline_data": {"mime_type": self.source["mime_type"], "data": self.source["base64"]}}

# 辅助函数
def encode_file_to_base64(file_content: bytes) -> str:
    return base64.b64encode(file_content).decode("utf-8")

def get_mime_type(file_path: str) -> str:
    extension = Path(file_path).suffix.lower() if '.' in file_path else '.bin'
    mime_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".mp4": "video/mp4",
        ".pdf": "application/pdf"
    }
    return mime_types.get(extension, "application/octet-stream")

# 占位函数，需外部实现
async def download_and_encode_file(url: str) -> Dict[str, str]:
    raise NotImplementedError("download_and_encode_file 必须由外部模块实现")

async def upload_to_gemini_media(file_content: bytes, mime_type: str) -> str:
    raise NotImplementedError("upload_to_gemini_media 必须由外部模块实现")