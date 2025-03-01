import logging
import json
import httpx
import random
import base64
from typing import List, Dict, Any, AsyncGenerator, Callable
from fastapi import HTTPException
from gemini_function_calls import handle_function_calls, TOOLS
from multimodal_classes import Text, Image, CustomFile
from chara_read import use_folder_chara

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 上传文件到 Gemini media.upload 端点
async def upload_to_gemini_media(file_content: bytes, mime_type: str, config) -> str:
    url = f"{config.api['llm']['gemini']['base_url']}/upload/v1beta/files?key={random.choice(config.api['llm']['gemini']['api_keys'])}"
    headers = {
        "Content-Type": mime_type,
        "X-Goog-Upload-Protocol": "raw"
    }
    async with httpx.AsyncClient(timeout=100) as client:
        response = await client.post(url, headers=headers, content=file_content)
        if response.status_code != 200:
            logger.error(f"文件上传失败: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=response.text)
        data = response.json()
        file_uri = data.get("file", {}).get("uri")
        if not file_uri:
            logger.error(f"未获取到 fileUri: {response.text}")
            raise HTTPException(status_code=500, detail="文件上传成功但未返回 fileUri")
        logger.info(f"文件上传成功，获取到 fileUri: {file_uri}")
        return file_uri

# 构造提示元素
async def gemini_prompt_elements_construct(message_list: List[Dict[str, Any]], config) -> List[Dict[str, Any]]:
    prompt_elements = []
    for item in message_list:
        if item["type"] == "text":
            prompt_elements.append({"text": item["content"]})
        elif item["type"] == "image":
            img = Image(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                        byte=item["source"]["byte"] if "byte" in item["source"] else None,
                        mime_type=item["source"].get("mime_type"))
            prompt_elements.append(await img.to_dict())
        elif item["type"] == "file":
            file = CustomFile(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                              byte=item["source"]["byte"] if "byte" in item["source"] else None,
                              mime_type=item["source"].get("mime_type"))
            base64_data = (await file.to_dict())["inline_data"]["data"]
            if len(base64.b64decode(base64_data)) > 20 * 1024 * 1024:
                file_uri = await upload_to_gemini_media(base64.b64decode(base64_data), file.source["mime_type"], config)
                prompt_elements.append({"fileData": {"mimeType": file.source["mime_type"], "fileUri": file_uri}})
            else:
                prompt_elements.append(await file.to_dict())
    return prompt_elements

# 非流式请求
async def gemini_request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable) -> str:
    base_url = config.api["llm"]["gemini"]["base_url"]
    api_key = random.choice(config.api["llm"]["gemini"]["api_keys"])
    model = config.api["llm"]["gemini"]["model"]
    url = f"{base_url}/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": history,
        "systemInstruction": {"parts": [{"text": config.api["llm"]["system"] or ""}]},
        "safetySettings": [
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
        ],
        "generationConfig": {
            "temperature": config.api["llm"]["gemini"]["temperature"],
            "topK": 40,
            "topP": 0.95,
            "maxOutputTokens": config.api["llm"]["gemini"]["maxOutputTokens"],
            "responseMimeType": "text/plain"
        }
    }
    if config.api["llm"]["func_calling"]:
        payload["tools"] = [{"function_declarations": TOOLS}]
    
    logger.info(f"发送非流式请求到: {url}")
    logger.debug(f"请求内容: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    headers = {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            logger.info(f"POST 返回内容: {response.text}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"非流式请求失败，状态码: {e.response.status_code}, 响应内容: {e.response.text}")
            raise
        data = response.json()
        
        if "error" in data:
            logger.error(f"API 返回错误: {data['error']['message']}")
            raise HTTPException(status_code=400, detail=data["error"]["message"])
        
        candidate = data["candidates"][0]["content"]
        parts = candidate.get("parts", [])
        
        if config.api["llm"]["func_calling"]:
            function_calls = [part["functionCall"] for part in parts if "functionCall" in part]
            if function_calls:
                history.append({
                    "role": "model",
                    "parts": [{"functionCall": fc} for fc in function_calls]
                })
                func_responses = await handle_function_calls(function_calls, config, client_id, send_message)
                history.append({
                    "role": "function",
                    "parts": func_responses
                })
                return await gemini_request(history, config, client_id, send_message)
        
        content = "".join(part["text"] for part in parts if "text" in part)
        if content:
            return content
        else:
            return "我会按你说的做。"

# 流式请求
async def gemini_stream_request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable, conversation_history: Dict[str, List[Dict[str, Any]]]) -> AsyncGenerator[str, None]:
    base_url = config.api["llm"]["gemini"]["base_url"]
    api_key = random.choice(config.api["llm"]["gemini"]["api_keys"])
    model = config.api["llm"]["gemini"]["model"]
    url = f"{base_url}/v1beta/models/{model}:streamGenerateContent?key={api_key}"
    payload = {
        "contents": history,
        "systemInstruction": {"parts": [{"text": config.api["llm"]["system"] or ""}]},
        "safetySettings": [
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
        ],
        "generationConfig": {
            "temperature": config.api["llm"]["gemini"]["temperature"],
            "topK": 40,
            "topP": 0.95,
            "maxOutputTokens": config.api["llm"]["gemini"]["maxOutputTokens"],
            "responseMimeType": "text/plain"
        }
    }
    if config.api["llm"]["func_calling"]:
        payload["tools"] = [{"function_declarations": TOOLS}]
    
    logger.info(f"发送流式请求到: {url}")
    logger.debug(f"请求内容: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    headers = {"Content-Type": "application/json"}

    async def generate() -> AsyncGenerator[str, None]:
        full_content = ""
        first_chunk_sent = False
        text_buffer = ""
        code_buffer = ""
        in_code_block = False
        json_buffer = ""
        function_calls = []

        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    logger.error(f"流式请求失败，状态码: {e.response.status_code}, 响应内容: {e.response.text}")
                    raise

                async for chunk in response.aiter_text():
                    logger.info(f"流式响应原始数据块: {chunk}")
                    cleaned_chunk = chunk.strip()
                    if cleaned_chunk == ']':
                        logger.info("收到流式响应结束标志 ']'")
                        break
                    if cleaned_chunk.startswith('[') and not json_buffer:
                        cleaned_chunk = cleaned_chunk[1:]
                    elif cleaned_chunk.startswith(','):
                        cleaned_chunk = cleaned_chunk[1:]
                    
                    json_buffer += cleaned_chunk
                    try:
                        data = json.loads(json_buffer)
                        json_buffer = ""
                        logger.debug(f"解析后的数据块: {json.dumps(data, ensure_ascii=False, indent=2)}")
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        
                        for part in parts:
                            if "text" in part:
                                content = part["text"]
                                # 将缓冲区和新内容合并处理
                                lines = (text_buffer + content).splitlines(keepends=True)
                                text_buffer = "" if content.endswith('\n') else lines[-1]
                                lines = lines[:-1] if text_buffer else lines

                                for line in lines:
                                    if line.strip():  # 仅处理非空行
                                        if in_code_block:
                                            if "```" in line:
                                                code_buffer += line.split("```")[0]
                                                full_content += f"```{code_buffer}```\n"
                                                yield f"data: {json.dumps({'content': f'```{code_buffer}```', 'start_stream': not first_chunk_sent, 'end_stream': False})}\n\n"
                                                first_chunk_sent = True
                                                in_code_block = False
                                                code_buffer = ""
                                                remaining = line.split("```", 1)[1]
                                                if remaining.strip():
                                                    full_content += remaining
                                                    yield f"data: {json.dumps({'content': remaining, 'start_stream': not first_chunk_sent, 'end_stream': False})}\n\n"
                                                    first_chunk_sent = True
                                            else:
                                                code_buffer += line
                                        else:
                                            if "```" in line:
                                                pre_content, _, code_start = line.partition("```")
                                                if pre_content.strip():
                                                    full_content += pre_content
                                                    yield f"data: {json.dumps({'content': pre_content, 'start_stream': not first_chunk_sent, 'end_stream': False})}\n\n"
                                                    first_chunk_sent = True
                                                in_code_block = True
                                                code_buffer = code_start
                                            else:
                                                full_content += line
                                                yield f"data: {json.dumps({'content': line, 'start_stream': not first_chunk_sent, 'end_stream': False})}\n\n"
                                                first_chunk_sent = True
                            elif "functionCall" in part and config.api["llm"]["func_calling"]:
                                function_calls.append(part["functionCall"])

                        if function_calls:
                            history.append({
                                "role": "model",
                                "parts": [{"functionCall": fc} for fc in function_calls]
                            })
                            func_responses = await handle_function_calls(function_calls, config, client_id, send_message)
                            history.append({
                                "role": "function",
                                "parts": func_responses
                            })
                            async for sub_chunk in await gemini_stream_request(history, config, client_id, send_message, conversation_history):
                                yield sub_chunk
                            return

                    except json.JSONDecodeError:
                        logger.debug("JSON 未完整，继续缓冲")
                        continue

                # 处理剩余缓冲区
                if text_buffer:
                    if text_buffer.strip():
                        full_content += text_buffer
                        yield f"data: {json.dumps({'content': text_buffer, 'start_stream': not first_chunk_sent, 'end_stream': False})}\n\n"
                        first_chunk_sent = True
                if in_code_block and code_buffer:
                    if code_buffer.strip():
                        full_content += f"```{code_buffer}```"
                        yield f"data: {json.dumps({'content': f'```{code_buffer}```', 'start_stream': not first_chunk_sent, 'end_stream': False})}\n\n"
                        first_chunk_sent = True

                # 只有当整个响应内容不为空时，才加入历史
                if full_content:
                    conversation_history.setdefault("default_user", []).append({
                        "role": "model",
                        "parts": [{"text": full_content}]
                    })
                    logger.info(f"流式响应总内容: {full_content}")
                else:
                    logger.info("流式响应总内容为空，不加入历史")

                # 发送结束信号
                yield f"data: {json.dumps({'content': '', 'start_stream': False, 'end_stream': True})}\n\n"
                logger.info("流式响应结束")

    return generate()