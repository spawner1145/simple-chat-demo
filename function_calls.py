import asyncio
import logging
from typing import List, Dict, Any, Callable
from multimodal_classes import Text, Image, CustomFile
import random
from engine_search import *
import platform
import subprocess

system = platform.system()

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
    
async def search_net(config, *args, client_id: str, send_message: Callable, **kwargs) -> Dict[str, Any]:
    """计算数学表达式的结果"""
    query = kwargs.get("query") if kwargs else args[0]["query"] if args else None
    if not query:
        return {"error": "缺少query参数"}
    try:
        final = ''
        functions = [
            baidu_search(query),
            searx_search(query)
        ]
        tasks = [asyncio.create_task(func) for func in functions]
        for future in asyncio.as_completed(tasks):
            try:
                result = await future
                if result:
                    final += result + '\n'
            except Exception as e:
                print(e)
        print(final)
        await send_message(client_id, [Text(f"搜索结果: {final}")])
        return {"result": final}
    except Exception as e:
        return {"error": f"计算错误: {str(e)}"}
    
async def read_html(config, *args, client_id: str, send_message: Callable, **kwargs) -> Dict[str, Any]:
    """读取HTML文件内容"""
    url = kwargs.get("url") if kwargs else args[0]["url"] if args else None
    if not url:
        return {"error": "缺少url参数"}
    try:
        html = await html_read(url,config)
        await send_message(client_id, [Text(f"HTML内容: {html}")])
        return {"result": html}
    except Exception as e:
        return {"error": f"读取HTML错误: {str(e)}"}
    
async def run_command(config, *args, client_id: str, send_message: Callable, **kwargs) -> Dict[str, Any]:
    """读取HTML文件内容"""
    command = kwargs.get("command") if kwargs else args[0]["command"] if args else None
    if not command:
        return {"error": "缺少command参数"}
    try:
        logs = ""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            read_stdout_task = asyncio.create_task(process.stdout.readline())
            read_stderr_task = asyncio.create_task(process.stderr.readline())
            while not process.stdout.at_eof() or not process.stderr.at_eof():
                done, pending = await asyncio.wait(
                    [read_stdout_task, read_stderr_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    line = task.result().decode('utf-8').strip()
                    if line:
                        logs += line + "\n"
                        print(f"[LOG] {line}")
                if not process.stdout.at_eof():
                    read_stdout_task = asyncio.create_task(process.stdout.readline())
                if not process.stderr.at_eof():
                    read_stderr_task = asyncio.create_task(process.stderr.readline())
            await process.wait()
        except Exception as e:
            logs += f"Error: {str(e)}\n"
        return {"result": f"命令执行日志{logs}"}
    except Exception as e:
        return {"error": f"读取HTML错误: {str(e)}"}

# 函数映射表
AVAILABLE_FUNCTIONS = {
    "get_weather": get_weather,
    "calculate": calculate,
    "read_html": read_html,
    "search_net": search_net,
    "run_command": run_command,
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
    },
    {
        "name": "search_net",
        "description": "当用户明确告知上网查或是你无法回答用户问题时，上网查询相关信息并总结(不要管点歌指令或是搜图指令)",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "你认为合适的上网查询的关键词或句子，注意，如果用户想知道当前时间，直接查询‘百度时间’；如果用户告知你要‘深度搜索’某一个内容，在调用此函数后获取到的所有url中选取你觉得合适的url，再调用read_html函数进行网页阅读"
                }
            },
            "required": [
                "query"
            ]
        }
    },
    {
        "name": "read_html",
        "description": "当需要阅读具体网址的内容时，调用此函数",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "需要阅读的url，注意你可以先判断一下这是不是一个合法的url，如果是一个下载链接，你不要阅读"
                }
            },
            "required": [
                "url"
            ]
        }
    },
    {
        "name": "run_command",
        "description": "当需要对本地环境进行操作时，如果可以命令行解决的问题，调用此函数，但需要确保命令行安全，危险的命令不要执行, 确保执行的命令短时间就能完成而不是消耗性能或时间的命令，如果想要对本地环境进行一些操作，比如打开浏览器或者删除某些文件复制某些文件，就可以调用此函数，同时由于我是在命令行中进行，理论上你也可以执行一些简单的代码，注意，由于你可以使用命令行，别说无法对本地环境进行操作，因为你可以使用命令行，所以你可以对本地环境进行操作，能用命令行就能完成本地环境的所有操作",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": f"需要执行的命令，请确保执行的是安全的命令，我是{system}系统，不需要说我无法进行xxx这种话，因为你可以使用命令行，所以你可以对本地环境进行操作，能用命令行就能完成本地环境的所有操作，如果不确定要调用什么命令，可以调用search_net和read_html函数来获取相关信息,当涉及到路径输入，用引号把完整的路径包含起来"
                }
            },
            "required": [
                "command"
            ]
        }
    },
]