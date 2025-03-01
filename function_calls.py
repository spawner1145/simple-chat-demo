import asyncio
import logging
from typing import List, Dict, Any, Callable
from multimodal_classes import Text, Image, CustomFile
import random

# 配置日志
logger = logging.getLogger(__name__)

# 可选函数定义
async def get_weather(config, *args, client_id: str, send_message: Callable, **kwargs) -> Dict[str, Any]:
    """获取指定城市的天气信息"""
    city = kwargs.get("city") if kwargs else args[0]["city"] if args else None
    if not city:
        return {"error": "缺少城市参数"}
    logger.info(f"获取 {city} 的天气信息")
    await send_message(client_id, [Text(f"正在查询 {city} 的天气...")])
    await asyncio.sleep(1)  # 模拟网络延迟
    result = {"weather": f"{city} 的天气：晴天，25°C"}
    await send_message(client_id, [Text(f"天气查询完成：{result['weather']}")])
    return result

async def calculate(config, *args, client_id: str, send_message: Callable, **kwargs) -> Dict[str, Any]:
    """计算数学表达式的结果"""
    expression = kwargs.get("expression") if kwargs else args[0]["expression"] if args else None
    if not expression:
        return {"error": "缺少表达式参数"}
    logger.info(f"计算表达式: {expression}")
    await send_message(client_id, [Text(f"正在计算: {expression}")])
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        await send_message(client_id, [Text(f"计算结果: {result}")])
        return {"result": result}
    except Exception as e:
        return {"error": f"计算错误: {str(e)}"}

# 函数映射表
AVAILABLE_FUNCTIONS = {
    "get_weather": get_weather,
    "calculate": calculate
}

async def handle_function_calls(function_calls: List[Dict[str, Any]], config, client_id: str, send_message: Callable) -> List[Dict[str, Any]]:
    """并行处理多个函数调用"""
    tasks = []
    for function_call in function_calls:
        func_name = function_call.get("name")
        args = function_call.get("args", {})
        logger.info(f"处理函数调用: {func_name}，参数: {args}")

        if func_name not in AVAILABLE_FUNCTIONS:
            tasks.append(asyncio.ensure_future(asyncio.sleep(0, result={"error": f"未知函数: {func_name}"})))
        else:
            tasks.append(asyncio.ensure_future(AVAILABLE_FUNCTIONS[func_name](config, client_id=client_id, send_message=send_message, **args)))

    results = await asyncio.gather(*tasks)
    return [
        {
            "functionResponse": {
                "name": function_call["name"],
                "response": result
            }
        }
        for function_call, result in zip(function_calls, results)
    ]

TOOLS = [
    {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名称"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "calculate",
        "description": "计算数学表达式的结果",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "数学表达式"}
            },
            "required": ["expression"]
        }
    }
]