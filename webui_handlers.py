import logging
from typing import List, Dict, Any, Callable
from multimodal_classes import Text, Image, CustomFile

# 配置日志
logger = logging.getLogger(__name__)

# WebUI 事件类
class WebUIEvent:
    def __init__(self, message_list: List[Dict[str, Any]], client_id: str):
        self.client_id = client_id
        self.plain = "".join(item["content"] for item in message_list if item["type"] == "text")
        self.image = [item for item in message_list if item["type"] == "image"]
        self.audio = [item for item in message_list if item["type"] == "audio"]
        self.video = [item for item in message_list if item["type"] == "video"]
        self.file = [item for item in message_list if item["type"] == "file"]

# WebUI 监听器列表
webui_listeners: List[Callable] = []

# WebUI 装饰器
def webui(func: Callable) -> Callable:
    webui_listeners.append(func)
    return func

# 测试处理器
@webui
async def on_message(event: WebUIEvent, send_message: Callable):
    logger.info(f"收到 WebUI 消息: {event.plain}")
    if "/test" in event.plain:
        # 使用 multimodal_classes 中的类发送测试消息
        image = Image(path=r'C:/Users/spawner/Downloads/《Break the Cocoon》封面.jpg')
        custom_file = CustomFile(path=r'C:/Users/spawner/Downloads/部署文档.pdf')
        await send_message(event.client_id, [
            Text("你好"),
            Text("！这是一个测试消息"),
            image,
            custom_file
        ])