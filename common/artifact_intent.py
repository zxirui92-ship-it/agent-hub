"""Conservative explicit visual-output hints, not a general intent router."""
import re


def image_requested(text):
    # Source/code and copywriting requests must not be turned into paid image jobs.
    text = re.sub(r'(?:不要|不需要|不必)(?:输出|返回|生成|提供)?(?:源代码|源码|代码|脚本|Markdown)', '', text, flags=re.I)
    if re.search(r'代码|脚本|源文件|HTML|SVG|Python|JavaScript|Markdown|文案|提示词|prompt|code|script', text, re.I):
        return False
    return bool(re.search(r'海报|生成一张图|画一张|插画|poster|generate an? image|'
                          r'(?:生成|制作|画|做成).{0,30}(?:图片|图像|配图)', text, re.I))
