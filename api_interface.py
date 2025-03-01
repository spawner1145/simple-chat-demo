import logging
import json
import httpx
import random
import base64
from typing import List, Dict, Any, AsyncGenerator, Callable
from fastapi import HTTPException
from function_calls import handle_function_calls, TOOLS
from multimodal_classes import *
from chara_read import use_folder_chara

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Gemini 文件上传 
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

# OpenAI 文件上传
async def upload_to_openai_media(file_content: bytes, mime_type: str, config) -> str:
    url = f"{config.api['llm']['openai']['base_url']}/files"
    headers = {
        "Authorization": f"Bearer {random.choice(config.api['llm']['openai']['api_keys'])}",
    }
    files = {
        "file": (f"file.{mime_type.split('/')[-1]}", file_content, mime_type),
        "purpose": (None, "assistants")
    }
    if config.api["proxy"]["http_proxy"]:
        proxies = {"http://": config.api["proxy"]["http_proxy"], "https://": config.api["proxy"]["http_proxy"]}
    else:
        proxies = None
    async with httpx.AsyncClient(timeout=100, proxies=proxies) as client:
        try:
            response = await client.post(url, headers=headers, files=files)
            response.raise_for_status()
            data = response.json()
            file_id = data.get("id")
            if not file_id:
                logger.error(f"未获取到 file_id: {response.text}")
                raise HTTPException(status_code=500, detail="文件上传成功但未返回 file_id")
            logger.info(f"文件上传成功，获取到 file_id: {file_id}")
            return file_id
        except httpx.HTTPStatusError as e:
            logger.error(f"文件上传失败: {e.response.text}")
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

# Gemini 提示元素构造
async def gemini_prompt_elements_construct(message_list: List[Dict[str, Any]], config) -> List[Dict[str, Any]]:
    logger.info(f"构造提示元素，输入消息列表: {json.dumps(message_list, indent=2)}")
    prompt_elements = []

    for item in message_list:
        if item["type"] == "text":
            prompt_elements.append({"text": item["content"]})
        elif item["type"] == "image":
            img = Image(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                        byte=item["source"]["byte"] if "byte" in item["source"] else None,
                        mime_type=item["source"].get("mime_type"))
            prompt_elements.append(await img.to_dict())  # 只返回 inline 数据
        elif item["type"] == "audio":
            audio = Audio(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                          byte=item["source"]["byte"] if "byte" in item["source"] else None,
                          mime_type=item["source"].get("mime_type"))
            base64_data = (await audio.to_dict())["inline_data"]["data"]
            if len(base64.b64decode(base64_data)) > 20 * 1024 * 1024:  # 示例阈值
                file_uri = await upload_to_gemini_media(base64.b64decode(base64_data), audio.source["mime_type"], config)
                prompt_elements.append({"fileData": {"mimeType": audio.source["mime_type"], "fileUri": file_uri}})
            else:
                prompt_elements.append(await audio.to_dict())
        elif item["type"] == "video":
            video = Video(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                          byte=item["source"]["byte"] if "byte" in item["source"] else None,
                          mime_type=item["source"].get("mime_type"))
            base64_data = (await video.to_dict())["inline_data"]["data"]
            if len(base64.b64decode(base64_data)) > 20 * 1024 * 1024:
                file_uri = await upload_to_gemini_media(base64.b64decode(base64_data), video.source["mime_type"], config)
                prompt_elements.append({"fileData": {"mimeType": video.source["mime_type"], "fileUri": file_uri}})
            else:
                prompt_elements.append(await video.to_dict())
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

    logger.info(f"生成的提示元素: {json.dumps(prompt_elements, indent=2)}")
    return prompt_elements

# OpenAI 提示元素构造
async def openai_prompt_elements_construct(message_list: List[Dict[str, Any]], config) -> List[Dict[str, Any]]:
    use_legacy_prompt = config.api["llm"]["openai"].get("使用旧版prompt结构", False)
    prompt_elements = []
    
    for item in message_list:
        if use_legacy_prompt:
            if item["type"] == "text":
                prompt_elements.append({"text": item["content"]})
            elif item["type"] in ["image", "file"]:
                logger.warning("使用旧版prompt结构，不支持多模态输入，忽略非文本内容")
        else:
            if item["type"] == "text":
                prompt_elements.append({"text": item["content"]})
            elif item["type"] == "image":
                img = Image(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                            byte=item["source"]["byte"] if "byte" in item["source"] else None,
                            mime_type=item["source"].get("mime_type"))
                base64_data = (await img.to_dict())["inline_data"]["data"]
                prompt_elements.append({
                    "image_url": {"url": f"data:{img.source['mime_type']};base64,{base64_data}"}
                })
            elif item["type"] == "audio":
                audio = Audio(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                            byte=item["source"]["byte"] if "byte" in item["source"] else None,
                            mime_type=item["source"].get("mime_type"))
                base64_data = (await audio.to_dict())["inline_data"]["data"]
                if len(base64.b64decode(base64_data)) > 20 * 1024 * 1024:  # 示例阈值
                    file_uri = await upload_to_openai_media(base64.b64decode(base64_data), audio.source["mime_type"],config)
                    prompt_elements.append({"fileData": {"mimeType": audio.source["mime_type"], "fileUri": file_uri}})
                else:
                    prompt_elements.append({"text": f"data:{audio.source['mime_type']};base64,{base64_data}"})
            elif item["type"] == "file":
                file = CustomFile(base64=item["source"]["base64"] if "base64" in item["source"] else None,
                                  byte=item["source"]["byte"] if "byte" in item["source"] else None,
                                  mime_type=item["source"].get("mime_type"))
                base64_data = (await file.to_dict())["inline_data"]["data"]
                if len(base64.b64decode(base64_data)) > 20 * 1024 * 1024:
                    file_id = await upload_to_openai_media(base64.b64decode(base64_data), file.source["mime_type"], config)
                    prompt_elements.append({"file_id": file_id})
                else:
                    prompt_elements.append({"text": f"data:{file.source['mime_type']};base64,{base64_data}"})
    return prompt_elements

# 统一的提示元素构造接口
async def prompt_elements_construct(message_list: List[Dict[str, Any]], config) -> List[Dict[str, Any]]:
    model_type = config.api["llm"]["model"]
    if model_type == "openai":
        return await openai_prompt_elements_construct(message_list, config)
    else:  # 默认 gemini
        return await gemini_prompt_elements_construct(message_list, config)

# Gemini 非流式请求
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
    if config.api["llm"]["gemini"]["func_calling"]:
        payload["tools"] = [{"function_declarations": TOOLS}]
    
    logger.info(f"发送非流式请求到: {url}")
    logger.debug(f"请求内容: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    headers = {"Content-Type": "application/json"}
    if config.api["proxy"]["http_proxy"]:
        proxies = {"http://": config.api["proxy"]["http_proxy"], "https://": config.api["proxy"]["http_proxy"]}
    else:
        proxies = None
    try:
        async with httpx.AsyncClient(timeout=30, proxies=proxies) as client:
            try:
                response = await client.post(url, json=payload, headers=headers)
                print(f"POST 返回内容: {response.text}")
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
            
            if config.api["llm"]["gemini"]["func_calling"]:
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
    except httpx.RequestError as e:
        logger.error(f"网络请求失败: {str(e)}")
        raise HTTPException(status_code=503, detail=f"无法连接到 API: {str(e)}")
    except httpx.HTTPStatusError as e:
        logger.error(f"API 返回状态错误: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)

# OpenAI 非流式请求
async def openai_request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable) -> str:
    base_url = config.api["llm"]["openai"]["base_url"]
    api_key = random.choice(config.api["llm"]["openai"]["api_keys"])
    model = config.api["llm"]["openai"]["model"]
    url = f"{base_url}/chat/completions"
    if config.api["proxy"]["http_proxy"]:
        proxies = {"http://": config.api["proxy"]["http_proxy"], "https://": config.api["proxy"]["http_proxy"]}
    else:
        proxies = None
    
    use_legacy_prompt = config.api["llm"]["openai"].get("使用旧版prompt结构", False)
    messages = []
    for msg in history:
        if use_legacy_prompt:
            text_content = "".join(part["text"] for part in msg["parts"] if "text" in part)
            if text_content:
                messages.append({"role": msg["role"], "content": text_content})
            elif "functionCall" in msg["parts"][0]:
                messages.append({
                    "role": msg["role"],
                    "content": None,
                    "tool_calls": [{
                        "type": "function",
                        "function": {
                            "name": msg["parts"][0]["functionCall"]["name"],
                            "arguments": json.dumps(msg["parts"][0]["functionCall"]["args"])
                        }
                    }]
                })
        else:
            content = []
            for part in msg["parts"]:
                if "text" in part:
                    content.append({"type": "text", "text": part["text"]})
                elif "image_url" in part:
                    content.append({"type": "image_url", "image_url": part["image_url"]})
                elif "file_id" in part:
                    content.append({"type": "text", "text": f"File ID: {part['file_id']}"})
                elif "functionCall" in part:
                    content.append({
                        "type": "function_call",
                        "function_call": {
                            "name": part["functionCall"]["name"],
                            "arguments": json.dumps(part["functionCall"]["args"])
                        }
                    })
            messages.append({"role": msg["role"], "content": content if content else None})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": config.api["llm"]["openai"]["temperature"],
        "max_tokens": config.api["llm"]["openai"]["maxOutputTokens"],
        "top_p": 0.95,
    }
    if config.api["llm"]["openai"]["func_calling"]:
        payload["tools"] = [{"type": "function", "function": tool} for tool in TOOLS]
        payload["tool_choice"] = "auto"
    
    logger.info(f"发送非流式请求到: {url}")
    print(f"请求内容: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    async with httpx.AsyncClient(timeout=30, proxies=proxies) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
            logger.info(f"POST 返回内容: {response.text}")
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"非流式请求失败，状态码: {e.response.status_code}, 响应内容: {e.response.text}")
            raise
        data = response.json()
        
        if "choices" not in data or not data["choices"]:
            logger.error(f"API 返回无有效响应: {data}")
            raise HTTPException(status_code=500, detail="API 返回无有效响应")
        
        choice = data["choices"][0]
        if "message" in choice:
            message = choice["message"]
            if message.get("tool_calls"):
                tool_calls = message["tool_calls"]
                history.append({
                    "role": "assistant",
                    "parts": [{"functionCall": {"name": call["function"]["name"], "args": json.loads(call["function"]["arguments"])}} for call in tool_calls]
                })
                func_responses = await handle_function_calls([{"name": call["function"]["name"], "args": json.loads(call["function"]["arguments"])} for call in tool_calls], config, client_id, send_message)
                history.append({
                    "role": "function",
                    "parts": func_responses
                })
                return await openai_request(history, config, client_id, send_message)
            content = message["content"]
            if config.api["llm"]["openai"]["COT"]:
                content = template.replace("{{reasoning_content}}",message["reasoning_content"]) + content
            return content if content else "我会按你说的做"
        return "错误，请清除记录"

# 统一的非流式请求接口
async def request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable) -> str:
    model_type = config.api["llm"]["model"]
    if model_type == "openai":
        return await openai_request(history, config, client_id, send_message)
    else:  # 默认 gemini
        return await gemini_request(history, config, client_id, send_message)

# Gemini 流式请求
async def gemini_stream_request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable, conversation_history: Dict[str, List[Dict[str, Any]]]) -> AsyncGenerator[str, None]:
    base_url = config.api["llm"]["gemini"]["base_url"]
    api_key = random.choice(config.api["llm"]["gemini"]["api_keys"])
    model = config.api["llm"]["gemini"]["model"]
    url = f"{base_url}/v1beta/models/{model}:streamGenerateContent?key={api_key}"
    if config.api["proxy"]["http_proxy"]:
        proxies = {"http://": config.api["proxy"]["http_proxy"], "https://": config.api["proxy"]["http_proxy"]}
    else:
        proxies = None
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
    if config.api["llm"]["gemini"]["func_calling"]:
        payload["tools"] = [{"function_declarations": TOOLS}]
    
    logger.info(f"发送流式请求到: {url}")
    logger.debug(f"请求内容: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    headers = {"Content-Type": "application/json"}

    async def generate() -> AsyncGenerator[str, None]:
        full_content = ""
        json_buffer = ""
        function_calls = []
        has_finished = False

        async with httpx.AsyncClient(timeout=30,proxies=proxies) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    logger.error(f"流式请求失败，状态码: {e.response.status_code}, 响应内容: {e.response.text}")
                    yield f"data: {json.dumps({'content': f'流式请求失败: {e.response.status_code} - {e.response.text}', 'start_stream': False, 'end_stream': True})}\n\n"
                    return

                yield f"data: {json.dumps({'content': '', 'start_stream': True, 'end_stream': False})}\n\n"
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
                        
                        # 解析并发送当前块的内容
                        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                        for part in parts:
                            if "text" in part:
                                content = part["text"]
                                full_content += content
                                logger.info(f"解析结果 - 当前块内容: {content}")
                                yield f"data: {json.dumps({'content': content, 'start_stream': False, 'end_stream': False})}\n\n"
                            elif "functionCall" in part and config.api["llm"]["gemini"]["func_calling"]:
                                function_calls.append(part["functionCall"])

                        # 检查是否结束，但不退出循环
                        if "finishReason" in data.get("candidates", [{}])[0] and data["candidates"][0]["finishReason"] == "STOP":
                            has_finished = True

                        # 处理函数调用
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
                            async for sub_chunk in gemini_stream_request(history, config, client_id, send_message, conversation_history):
                                yield sub_chunk
                            return

                    except json.JSONDecodeError:
                        logger.debug("JSON 未完整，继续缓冲")
                        continue

                # 所有块解析完成后发送结束标志
                if full_content:
                    conversation_history.setdefault("default_user", []).append({
                        "role": "model",
                        "parts": [{"text": full_content}]
                    })
                    logger.info(f"流式响应总内容: {full_content}")
                yield f"data: {json.dumps({'content': '', 'start_stream': False, 'end_stream': True})}\n\n"
                logger.info("流式响应结束")

    return generate()

# OpenAI 流式请求
async def openai_stream_request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable, conversation_history: Dict[str, List[Dict[str, Any]]]) -> AsyncGenerator[str, None]:
    base_url = config.api["llm"]["openai"]["base_url"]
    api_key = random.choice(config.api["llm"]["openai"]["api_keys"])
    model = config.api["llm"]["openai"]["model"]
    url = f"{base_url}/chat/completions"
    if config.api["proxy"]["http_proxy"]:
        proxies = {"http://": config.api["proxy"]["http_proxy"], "https://": config.api["proxy"]["http_proxy"]}
    else:
        proxies = None
    
    use_legacy_prompt = config.api["llm"]["openai"].get("使用旧版prompt结构", False)
    messages = []
    for msg in history:
        if use_legacy_prompt:
            text_content = "".join(part["text"] for part in msg["parts"] if "text" in part)
            if text_content:
                messages.append({"role": msg["role"], "content": text_content})
            elif "functionCall" in msg["parts"][0]:
                messages.append({
                    "role": msg["role"],
                    "content": None,
                    "tool_calls": [{
                        "type": "function",
                        "function": {
                            "name": msg["parts"][0]["functionCall"]["name"],
                            "arguments": json.dumps(msg["parts"][0]["functionCall"]["args"])
                        }
                    }]
                })
        else:
            content = []
            for part in msg["parts"]:
                if "text" in part:
                    content.append({"type": "text", "text": part["text"]})
                elif "image_url" in part:
                    content.append({"type": "image_url", "image_url": part["image_url"]})
                elif "file_id" in part:
                    content.append({"type": "text", "text": f"File ID: {part['file_id']}"})
                elif "functionCall" in part:
                    content.append({
                        "type": "function_call",
                        "function_call": {
                            "name": part["functionCall"]["name"],
                            "arguments": json.dumps(part["functionCall"]["args"])
                        }
                    })
            messages.append({"role": msg["role"], "content": content if content else None})
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": config.api["llm"]["openai"]["temperature"],
        "max_tokens": config.api["llm"]["openai"]["maxOutputTokens"],
        "top_p": 0.95,
        "stream": True
    }
    if config.api["llm"]["openai"]["func_calling"]:
        payload["tools"] = [{"type": "function", "function": tool} for tool in TOOLS]
        payload["tool_choice"] = "auto"
    
    logger.info(f"发送流式请求到: {url}")
    logger.debug(f"请求内容: {json.dumps(payload, ensure_ascii=False, indent=2)}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    async def generate() -> AsyncGenerator[str, None]:
        full_content = ""
        is_first_chunk = True
        function_calls = []

        async with httpx.AsyncClient(timeout=30,proxies=proxies) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    logger.error(f"流式请求失败，状态码: {e.response.status_code}, 响应内容: {e.response.text}")
                    yield f"data: {json.dumps({'content': f'流式请求失败: {e.response.status_code} - {e.response.text}', 'start_stream': False, 'end_stream': True})}\n\n"
                    return

                yield f"data: {json.dumps({'content': '', 'start_stream': True, 'end_stream': False})}\n\n"
                async for chunk in response.aiter_lines():
                    if not chunk.strip():
                        continue
                    logger.info(f"流式响应原始数据块: {chunk}")
                    cleaned_chunk = chunk.strip()

                    if cleaned_chunk.startswith('data: '):
                        data_str = cleaned_chunk[len('data: '):]
                        if data_str == '[DONE]':
                            if full_content:
                                conversation_history.setdefault("default_user", []).append({
                                    "role": "assistant",
                                    "parts": [{"text": full_content}]
                                })
                                logger.info(f"流式响应总内容已写入历史: {full_content}")
                            yield f"data: {json.dumps({'content': '', 'start_stream': False, 'end_stream': True})}\n\n"
                            logger.info("流式响应结束")
                            return

                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta and delta["content"]:
                                content = delta["content"]
                                full_content += content
                                logger.info(f"解析结果 - 当前块内容: {content}")
                                yield f"data: {json.dumps({'content': content, 'start_stream': False, 'end_stream': False})}\n\n"
                            elif "tool_calls" in delta:
                                tool_calls = delta.get("tool_calls", [])
                                for tool_call in tool_calls:
                                    if "function" in tool_call:
                                        function_calls.append({
                                            "name": tool_call["function"]["name"],
                                            "args": json.loads(tool_call["function"]["arguments"])
                                        })

                            if data.get("choices", [{}])[0].get("finish_reason") == "tool_calls" and function_calls:
                                history.append({
                                    "role": "assistant",
                                    "parts": [{"functionCall": {"name": fc["name"], "args": fc["args"]}} for fc in function_calls]
                                })
                                func_responses = await handle_function_calls(function_calls, config, client_id, send_message)
                                history.append({
                                    "role": "function",
                                    "parts": func_responses
                                })
                                async for sub_chunk in openai_stream_request(history, config, client_id, send_message, conversation_history):
                                    yield sub_chunk
                                return

                        except json.JSONDecodeError:
                            logger.debug("JSON 未完整，继续缓冲")

                # 所有块解析完成后发送结束标志
                if full_content:
                    conversation_history.setdefault("default_user", []).append({
                        "role": "assistant",
                        "parts": [{"text": full_content}]
                    })
                    logger.info(f"流式响应总内容: {full_content}")
                yield f"data: {json.dumps({'content': '', 'start_stream': False, 'end_stream': True})}\n\n"
                logger.info("流式响应结束")

    return generate()

# 统一的流式请求接口
async def stream_request(history: List[Dict[str, Any]], config, client_id: str, send_message: Callable, conversation_history: Dict[str, List[Dict[str, Any]]]) -> AsyncGenerator[str, None]:
    model_type = config.api["llm"]["model"]
    if model_type == "openai":
        return await openai_stream_request(history, config, client_id, send_message, conversation_history)
    else:  # 默认 gemini
        return await gemini_stream_request(history, config, client_id, send_message, conversation_history)
    
template = """
<details>
<summary>思考过程</summary>
---
{{reasoning_content}}
---
</details>
"""