import argparse
import os
import logging
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uuid
import uvicorn
import json
from typing import List, Dict, Any
import asyncio

# 导入模块
import multimodal_classes
from multimodal_classes import Text, download_and_encode_file
from gemini_function_calls import handle_function_calls, TOOLS
from webui_handlers import webui_listeners, WebUIEvent
from gemini_api import gemini_request, gemini_stream_request, gemini_prompt_elements_construct, upload_to_gemini_media
from yamlLoader import YAMLManager

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化 FastAPI 应用
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局变量
conversation_history: Dict[str, List[Dict[str, Any]]] = {}
clients: Dict[str, WebSocket] = {}
config = YAMLManager(["config/api.yaml"])  # 初始化 config

# 发送消息到 WebSocket 客户端
async def send_message(client_id: str, message_list: List[Any], is_streaming: bool = False):
    if client_id not in clients:
        logger.warning(f"客户端 {client_id}: 不存在，跳过发送")
        return

    if not is_streaming:
        combined_messages = []
        text_content = ""

        for msg in message_list:
            if hasattr(msg, 'to_dict'):
                if asyncio.iscoroutinefunction(msg.to_dict):
                    msg_dict = await msg.to_dict()
                else:
                    msg_dict = msg.to_dict()
                if "text" in msg_dict:
                    text_content += msg_dict["text"]
                elif "inline_data" in msg_dict:
                    mime_type = msg_dict["inline_data"]["mime_type"]
                    filename = getattr(msg, "source", {}).get("filename", "unknown_file")
                    if mime_type.startswith("image/"):
                        combined_messages.append({
                            "type": "image",
                            "source": {
                                "base64": msg_dict["inline_data"]["data"],
                                "mime_type": mime_type,
                                "filename": filename
                            }
                        })
                    elif mime_type.startswith("audio/"):
                        combined_messages.append({
                            "type": "audio",
                            "source": {
                                "base64": msg_dict["inline_data"]["data"],
                                "mime_type": mime_type,
                                "filename": filename
                            }
                        })
                    elif mime_type.startswith("video/"):
                        combined_messages.append({
                            "type": "video",
                            "source": {
                                "base64": msg_dict["inline_data"]["data"],
                                "mime_type": mime_type,
                                "filename": filename
                            }
                        })
                    else:
                        combined_messages.append({
                            "type": "file",
                            "source": {
                                "base64": msg_dict["inline_data"]["data"],
                                "mime_type": mime_type,
                                "filename": filename
                            }
                        })
                elif "fileData" in msg_dict:
                    filename = getattr(msg, "source", {}).get("filename", "uploaded_file")
                    combined_messages.append({
                        "type": "file",
                        "source": {
                            "fileUri": msg_dict["fileData"]["fileUri"],
                            "mime_type": msg_dict["fileData"]["mimeType"],
                            "filename": filename
                        }
                    })
            else:
                combined_messages.append(msg)

        if text_content:
            combined_messages.insert(0, {"type": "text", "content": text_content})

        if combined_messages:
            message_json = json.dumps(combined_messages)
            await clients[client_id].send_text(message_json)
            logger.info(f"客户端 {client_id}: 非流式消息已发送: {message_json}")
    else:
        # 保留当前的流式消息发送逻辑
        async for chunk in message_list:
            await clients[client_id].send_text(chunk)
            logger.info(f"客户端 {client_id}: 流式数据块已发送: {chunk}")
            await asyncio.sleep(0.1)

# WebSocket 端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    client_id = str(uuid.uuid4())
    clients[client_id] = websocket
    logger.info(f"客户端 {client_id} 已连接")
    
    await send_message(client_id, [Text("已连接到服务器")])

    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"从客户端 {client_id} 接收到消息: {data}")
            message_data = json.loads(data)
            await handle_message(client_id, message_data)
    except Exception as e:
        await send_message(client_id, [Text(f"WebSocket 错误: {str(e)}")])
    finally:
        del clients[client_id]
        logger.info(f"客户端 {client_id} 已断开")

# 处理 WebSocket 消息
async def handle_message(client_id: str, message_data: Dict[str, Any]):
    message_list = message_data.get("message", [])
    is_streaming = message_data.get("isStreaming", False)

    if not message_list:
        logger.warning(f"客户端 {client_id}: 消息列表为空，跳过处理")
        await send_message(client_id, [Text("消息为空，无法处理")])
        return

    # 处理 WebUI 事件
    event = WebUIEvent(message_list, client_id)
    for listener in webui_listeners:
        try:
            logger.debug(f"客户端 {client_id}: 调用监听函数: {listener.__name__}")
            await listener(event, send_message)
        except Exception as e:
            logger.error(f"客户端 {client_id}: 监听函数 {listener.__name__} 执行错误: {str(e)}")

    # 检查是否以 "/" 开头
    first_message = next((item["content"] for item in message_list if item["type"] == "text"), "")
    if first_message.startswith("/"):
        logger.info(f"客户端 {client_id}: 消息以 '/' 开头: {first_message}")
        # 处理 /clear 命令
        if len(message_list) == 1 and message_list[0].get("type") == "text" and message_list[0].get("content") == "/clear":
            logger.info(f"客户端 {client_id}: 接收到清除命令，清除对话历史")
            conversation_history["default_user"] = []
            await send_message(client_id, [Text("聊天记录已清除")])
        return

    user_id = "default_user"
    if user_id not in conversation_history:
        logger.info(f"客户端 {client_id}: 初始化新对话历史，用户: {user_id}")
        conversation_history[user_id] = []

    current_prompt = await gemini_prompt_elements_construct(message_list, config)
    history = conversation_history[user_id]
    history.append({"role": "user", "parts": current_prompt})

    if is_streaming:
        stream_generator = await gemini_stream_request(history, config, client_id, send_message, conversation_history)
        await send_message(client_id, stream_generator, is_streaming=True)
    else:
        try:
            answer = await gemini_request(history, config, client_id, send_message)
            history.append({"role": "model", "parts": [{"text": answer}]})
            conversation_history[user_id] = history[-50:]
            await send_message(client_id, [Text(answer)])
        except Exception as e:
            await send_message(client_id, [Text(f"处理错误: {str(e)}")])

# 主函数
def main():
    parser = argparse.ArgumentParser(description="启动 AI 聊天后端服务器")
    parser.add_argument("--port", type=int, default=8000, help="服务器运行的端口号")
    args = parser.parse_args()

    port = args.port
    if not (1 <= port <= 65535):
        port = 8000

    app.mount("/", StaticFiles(directory=os.path.dirname(__file__), html=True), name="static")
    uvicorn.run(app, host="127.0.0.1", port=port)

# 注入实现
multimodal_classes.download_and_encode_file = download_and_encode_file
multimodal_classes.upload_to_gemini_media = upload_to_gemini_media

if __name__ == "__main__":
    main()