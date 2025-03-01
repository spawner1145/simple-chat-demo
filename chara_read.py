import re
from PIL import Image
import html
import base64
import os

async def use_folder_chara(file_name):
    full_path = f"chara/{file_name}"
    if file_name.endswith((".txt", ".json")):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    elif file_name.endswith((".jpg", ".jpeg", ".png")):
        return silly_tavern_card(full_path, clear_html=True)


async def get_folder_chara():
    chara_list = [f for f in os.listdir('chara')]
    return "\n".join(chara_list)


def clean_invalid_characters(s, clear_html=False):
    """
    清理字符串中的无效控制字符，并根据需要移除HTML标签及其内容，以及前面可能存在的'xxx:'或'xxx：'前缀。
    """
    cleaned = ''.join(c for c in s if ord(c) >= 32 or c in ('\t', '\n', '\r'))
    if clear_html:
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r'<[^>]+>.*?</[^>]+>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'<[^>]+?/>', '', cleaned)
        cleaned = re.sub(r'^.*?(?=:|：)', '', cleaned).lstrip(':： ').lstrip()
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n\s+', '\n', cleaned)

    cleaned = cleaned.replace('{{user}}', '{用户}').replace('{{char}}', '{bot_name}')

    return cleaned.strip()


def silly_tavern_card(image_path, clear_html=False):
    image = Image.open(image_path)
    # 打印基本信息
    # print("图片基本信息:")
    # print(f"格式: {image.format}")
    # print(f"大小: {image.size}")
    # print(f"模式: {image.mode}")

    # 打印所有图像信息
    # print("\n所有图像信息:")
    # for key, value in image.info.items():
    # print(f"{key}: {value}")

    # 尝试打印文本块
    try:
        print("\n文本块信息:")
        for k, v in image.text.items():
            print(f"{k}: {len(v)} 字符")
            # 如果文本很长，只打印前100个字符
            print(f"预览: {v[:100]}...")
            pass
    except AttributeError:
        return "错误，没有文本块信息"

    final = []

    # 尝试解码 base64
    try:
        for key, value in image.info.items():
            if isinstance(value, str) and 'chara' in key.lower():
                print(f"\n尝试解码 {key} 的 base64:")
                decoded = base64.b64decode(value)
                res = decoded.decode('utf-8', errors='ignore')
                final.append(res)

    except Exception as e:
        return (f"错误，解码失败: {e}")

    if final:
        s = "\n".join(final)
        return clean_invalid_characters(s, clear_html=False)
    else:
        return "错误，没有人设信息"