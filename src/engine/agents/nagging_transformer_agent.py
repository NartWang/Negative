"""Nagging Transformer Agent (v3.6).

Takes a piece of "唠叨"—a parent's worry-driven message such as a forwarded health
article, a check-in question, or a sleep nag—and turns it into three different
ways the child can respond, all of which:
  1. acknowledge the parent's love
  2. avoid the "lecture / interrogation" frame
  3. give the parent a concrete handhold to feel needed

The three styles map to the spec's "反客为主" strategies:
  - help_request:  把"担心"翻译成"求助"，让对方感到被需要
  - co_challenge:  把"催促/说教"翻译成"我们一起来做"，对等的共同任务
  - warm_echo:     直接共情温柔回应，不躲、不挑战、不敷衍
"""

import json
import re
from agents.diary_agent import (
    AIEmptyResponseError,
    AIResponseError,
    request_chat_completion,
)


_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_UNTERMINATED_THINK_RE = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)
_LEFTOVER_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _UNTERMINATED_THINK_RE.sub("", cleaned)
    cleaned = _LEFTOVER_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def _extract_json(text: str) -> str:
    """Try to pull JSON out of fences or stray prose."""
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # Find the first { and the matching last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text.strip()


SYSTEM_PROMPT = """你是一个家庭沟通教练。你的任务：帮年轻人用**像他自己嘴里会说出来的话**回应父母的"焦虑式关心"。

# 产品理念（必须吃透）
父母转发养生文、反复问"吃饭了吗"、催早睡催相亲——这些表面是说教，**本质是他们不知道怎么表达爱**。
我们不是要替孩子写一段冷冰冰的"模板回复"，而是把这份没说出口的爱，翻译成孩子真的会在微信里敲出来的样子。

# 风格底线 —— 这一条违反了一切都白搭

**真实，比正确重要。**

绝对不要写出这种 AI 腔的回复：
- ❌ "妈，看到你这么担心我，真的挺感动的。"（谁会跟妈说"挺感动的"？）
- ❌ "我决定明天开始调整作息。"（"调整作息" 是开会用语）
- ❌ "每天 11 点前互相道晚安"（"互相" 太书面）
- ❌ "感谢您的关心"、"我会注意的"（公文）
- ❌ 每条都以问句结尾、每条都先称呼再感谢再正文——**结构对称就是 AI 味的根源**

你要写出来的样子，像这种：
- ✅ "妈我看到了。最近确实有点上火，你以前是不是用过那个什么菊花决明子？给我念念配方"
- ✅ "哎那我也催你！咱俩说好今晚都 11 点关灯，我设闹钟，第二天截图对账"
- ✅ "刚加完班蹲电梯里呢。你发这个我看完笑了，但确实该收手了"

具体怎么写：
- **不必每条都从"妈"开头** —— 真实微信里常常直接进正文
- **允许口头语**："哎"、"嗯"、"……"、"行吧"、"哈哈"、"完了"、"得"、"诶"
- **允许不完整句**："不是吧妈"、"行 听你的"、"那你呢"
- **长度自由** —— 一句话回完也行（15 字），多一句铺垫也行（最多 80 字），但**不要为了凑字数堆形容词**
- **可以承认累、承认烦、承认还没做到** —— 真实的人不会假装完美。但承认完要有个小动作或小决定，让妈觉得你听进去了
- **细节胜于抒情** —— 与其说"我也想你"，不如说"刚才路过那家卤味店"
- **称呼跟着输入走** —— 输入说"妈妈"就用"妈"，"爸爸"就用"爸"

# 三种回应风格

1. **help_request（担心 → 求助）**
   把父母的"担心"翻译成你的"求助"。让父母从"被推开的关心者"变成"被孩子需要的智囊"。
   关键：求助要**具体到一个动作或一个方子**，不能是"你教教我吧"这种空泛的求助。

2. **co_challenge（说教 → 协同）**
   把父母单方面的催促，翻译成"我们一起做"的对等挑战。
   关键：挑战要**轻、好玩、可执行**——不是"我们一起健身吧"这种宏大誓言，而是"今晚都 11 点关灯，截图对账"这种小到第二天就能跟进的小约定。

3. **warm_echo（直接共情）**
   不躲不挑，给妈/爸一句温暖的回应。
   关键：必须带一个**今天刚发生的、具体的、能被追问的小细节**——食堂阿姨多给一勺、地铁里看到的小狗、加班点的那家外卖。空洞的"我也很想你"不算。

# 硬要求（违反 = 失败）
- 每条 15-80 字（短到 15 字也可以，绝不强行凑长）
- 不要每条都问句结尾
- 不要每条都从称呼开头
- 不要用"调整作息"、"加强锻炼"、"注意身体"这类公文式表达
- 不要堆"真的"、"挺"、"非常"、"真的挺"这种 AI 模板副词
- 输出**合法 JSON**，不要任何解释、前后文、markdown 围栏

输出格式：
{
  "help_request": "...",
  "co_challenge": "...",
  "warm_echo": "..."
}
"""


async def transform_nagging(nag_text: str, relation: str = "妈妈") -> dict:
    """Turn one piece of nagging into 3 response cards.

    Returns:
        {"help_request": str, "co_challenge": str, "warm_echo": str}

    Raises a typed generation error when the provider output is unusable.
    """
    user_message = f"""父母（关系：{relation}）刚刚发来的话：
"{nag_text}"

请生成三种回应卡片，输出 JSON。"""

    raw = await request_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.85,
        max_tokens=2000,
        timeout=60,
    )

    cleaned = _strip_reasoning(raw)
    json_str = _extract_json(cleaned)

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        raise AIResponseError(
            "AI service returned an invalid response"
        ) from None

    if not isinstance(parsed, dict):
        raise AIResponseError("AI service returned an invalid response")

    required = ("help_request", "co_challenge", "warm_echo")
    missing = set(required) - parsed.keys()
    if missing:
        raise AIResponseError("AI service returned an invalid response")

    cards = {}
    for key in required:
        value = parsed[key]
        if not isinstance(value, str):
            raise AIResponseError("AI service returned an invalid response")
        value = value.strip()
        if not value:
            raise AIEmptyResponseError("AI service returned empty content")
        cards[key] = value
    return cards
