#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 社区模拟机器人（流水席版 · 完整整合）

特性：
  1. 所有内容（网名/简介/帖子/评论）由 LLM 实时生成，网名风格对标小红书/X；
  2. 注册时自动编网名 + 从网络抓真实图片上传头像（头像失败=终止程序）；
  3. 发帖随机 0~9 张图：无图=综合历史性格发帖，有图=看图写文（VLM最多3张图防内存溢出）；
  4. 流水席模型：账号池 N 人，同时在线 M 人，每人"上线刷一会 -> 随机点赞/评论/发帖 -> 下线"；
  5. 多线程安全：LLM 信号量限流 + 状态文件锁 + 点赞防 toggle（isLike 判断）；
  6. 长期关系记忆：记录好感度与熟悉度，影响后续互动策略；
  7. 国籍与语言偏好：绑定国籍，优先浏览同语言内容，使用对应语言生成内容；
  8. 本地兴趣决策：按人格、语言、兴趣和关系选择真实浏览，并上报 Bowall 浏览/停留数据。

依赖：仅 Python 标准库。

用法：
  export BOT_LLM_KEY=sk-xxxx
  export BOWALL_BASE=http://localhost:8080
  python tools/ai_community_bot.py --agents 100 --concurrent 5
"""

import argparse
import base64
import concurrent.futures
import gc
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------
BASE = os.environ.get("BOWALL_BASE", "http://localhost:8080")
UA = {"User-Agent": "Mozilla/5.0 (compatible; AiCommunityBot/1.0)"}

LLM_URL = os.environ.get("BOT_LLM_URL", "https://api.deepseek.com/chat/completions")
LLM_KEY = os.environ.get("BOT_LLM_KEY", "sk-15782c1f893144c9b3868f8074c7c5f6")
LLM_MODEL = os.environ.get("BOT_LLM_MODEL", "deepseek-chat")

# 可选：视觉模型（配置后"看图写文"为真看图；不配置用主题+标题描述代替）
VLM_URL = os.environ.get("BOT_VLM_URL", "")
VLM_KEY = os.environ.get("BOT_VLM_KEY", "")
VLM_MODEL = os.environ.get("BOT_VLM_MODEL", "")

# 帖子图片源：Wikimedia Commons 分类（同分类=同风格，免 key 直链）
IMAGE_TOPICS = [
    ("Coffee", "咖啡馆/手冲咖啡的暖色调照片"),
    ("Cats", "家猫日常照片"),
    ("Sunset", "日落晚霞风景照"),
    ("Street food", "街头小吃/夜市食物照片"),
    ("City skyline at night", "城市夜景天际线"),
    ("Houseplant", "室内绿植/阳台盆栽"),
    ("Bicycle", "骑行/街边自行车"),
    ("Beach", "海边沙滩风景"),
    ("Mountain hiking", "登山徒步山景"),
    ("Books", "书桌/书架/阅读角落"),
]
ALLOWED_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif"}

# 头像源：真实网络图片（后端 ImageIO 只收 jpg/png/gif）
GITHUB_AVATARS = [
    "torvalds", "sindresorhus", "yyx990803", "mrdoob", "addyosmani",
    "kentcdodds", "wesbos", "bradtraversy", "golang", "rust-lang",
    "python", "nodejs", "vercel", "tailwindlabs", "microsoft", "google",
]

# 新增：国籍与语言池
NATIONALITIES = [
    {"country": "中国", "language": "中文", "lang_code": "zh", "prompt_lang": "简体中文"},
    {"country": "美国", "language": "English", "lang_code": "en", "prompt_lang": "English"},
    {"country": "日本", "language": "日本語", "lang_code": "ja", "prompt_lang": "日本語"},
    {"country": "韩国", "language": "한국어", "lang_code": "ko", "prompt_lang": "한국어"},
    {"country": "法国", "language": "Français", "lang_code": "fr", "prompt_lang": "Français"},
    {"country": "德国", "language": "Deutsch", "lang_code": "de", "prompt_lang": "Deutsch"},
    {"country": "俄罗斯", "language": "Русский", "lang_code": "ru", "prompt_lang": "Русский"},
    {"country": "西班牙", "language": "Español", "lang_code": "es", "prompt_lang": "Español"},
]


# 新增：简单的基于正则的语言检测 (无需第三方库)
def detect_lang(text: str) -> str:
    if not text: return "unknown"
    if re.search(r'[\u4e00-\u9fff]', text): return "zh"
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text): return "ja"
    if re.search(r'[\uAC00-\uD7AF]', text): return "ko"
    if re.search(r'[\u0400-\u04FF]', text): return "ru"
    if re.search(r'[àâäéèêëïîôùûüÿçœæñ]', text, re.I): return "es"
    return "en"


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")

# 并发控制：LLM 限流信号量 + 状态文件锁
llm_semaphore = threading.Semaphore(3)
state_lock = threading.Lock()
# 头像下载全局节流
avatar_lock = threading.Lock()
_last_avatar_ts = [0.0]
AVATAR_MIN_GAP = float(os.environ.get("BOT_AVATAR_GAP", "8"))


def throttle_avatar():
    with avatar_lock:
        now = time.time()
        wait = AVATAR_MIN_GAP - (now - _last_avatar_ts[0])
        if wait > 0:
            time.sleep(wait)
        _last_avatar_ts[0] = time.time()


# 会话行为概率（main 中按命令行参数覆盖）
SESSION_CFG = {"like": 0.40, "comment": 0.15, "post": 0.10}

# 浏览兴趣标签只用于本地行为决策；不会让每次刷帖都额外请求 LLM。
INTEREST_KEYWORDS = {
    "tech": ("ai", "人工智能", "代码", "编程", "开源", "模型", "科技", "产品", "startup", "code", "tech"),
    "travel": ("旅行", "旅游", "徒步", "山", "海", "城市", "风景", "旅", "trip", "travel", "beach", "mountain"),
    "food": ("美食", "咖啡", "餐厅", "吃", "料理", "夜市", "food", "coffee", "cafe", "recipe"),
    "photo": ("照片", "摄影", "相机", "胶片", "光影", "photo", "camera", "film", "street"),
    "music": ("音乐", "歌曲", "演出", "乐队", "专辑", "music", "song", "album", "concert"),
    "books": ("阅读", "书", "电影", "播客", "小说", "book", "reading", "movie", "podcast"),
    "fitness": ("跑步", "健身", "骑行", "运动", "瑜伽", "run", "fitness", "cycling", "yoga"),
    "life": ("日常", "生活", "宠物", "猫", "狗", "植物", "家", "daily", "life", "cat", "dog"),
}
PERSONALITY_DWELL_BIAS = {
    "好奇": 0.16, "话痨": 0.12, "热情": 0.10, "认真": 0.14, "内向": 0.05,
    "高冷": -0.08, "社恐": -0.05, "随性": 0.02, "幽默": 0.06,
}


# ---------------------------------------------------------------------------
# 基础网络层
# ---------------------------------------------------------------------------
def http_download(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_multipart(method: str, path: str, fields: dict, file_field: str,
                   filename: str, file_bytes: bytes, content_type: str, token=None):
    url = BASE + path
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n"
                     f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
    parts.append((f"--{boundary}\r\n"
                  f'Content-Disposition: form-data; name="{file_field}"; '
                  f'filename="{filename}"\r\n'
                  f"Content-Type: {content_type}\r\n\r\n").encode("utf-8"))
    parts.append(file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [upload] {method} {path} -> {e.code}: "
              f"{e.read().decode('utf-8', 'ignore')[:200]}", file=sys.stderr)
    except Exception as e:
        print(f"  [upload] {method} {path} -> {e}", file=sys.stderr)
    return None


class ApiError(Exception):
    pass


def http_json(method: str, path: str, body=None, token=None, params=None, raise_on_error=False):
    url = BASE + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [http] {method} {path} -> {e.code}: "
              f"{e.read().decode('utf-8', 'ignore')[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [http] {method} {path} -> {e}", file=sys.stderr)
        return None
    if isinstance(r, dict) and r.get("code") not in (1, None):
        msg = r.get("msg")
        if raise_on_error:
            raise ApiError(f"{method} {path}: {msg}")
        print(f"  [api] {method} {path} -> code={r.get('code')} msg={msg}", file=sys.stderr)
    return r


# ---------------------------------------------------------------------------
# LLM 接入层
# ---------------------------------------------------------------------------
def llm_generate(prompt: str, max_retry: int = 5):
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.1,
        "max_tokens": 200,
    }).encode("utf-8")
    for i in range(max_retry):
        with llm_semaphore:
            try:
                req = urllib.request.Request(LLM_URL, data=payload, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {LLM_KEY}",
                })
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    return d["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 10 * (i + 1)
                    print(f"  [llm] 触发限流(429)，等待 {wait}s 重试…", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"  [llm] 第{i + 1}次失败: HTTP {e.code}", file=sys.stderr)
                    time.sleep(2 + i)
            except Exception as e:
                print(f"  [llm] 第{i + 1}次失败: {e}", file=sys.stderr)
                time.sleep(2 + i)
    sys.exit("[致命] LLM 调用连续失败，已中止。")


def llm_vision_generate(items: list, prompt: str):
    if not (VLM_URL and VLM_KEY):
        return None
    content = [{"type": "text", "text": prompt}]
    for b64, ctype in items:
        content.append({"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}})
    payload = json.dumps({"model": VLM_MODEL,
                          "messages": [{"role": "user", "content": content}],
                          "temperature": 1.0, "max_tokens": 200}).encode("utf-8")
    try:
        req = urllib.request.Request(VLM_URL, data=payload, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {VLM_KEY}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [vlm] 视觉模型调用失败，退回描述模式: {e}", file=sys.stderr)
        return None


def _clean_llm_text(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    return s.strip().strip("`").strip("\"'“”").strip()


# ---------------------------------------------------------------------------
# 帖子图片：同风格抓取 + 全局去重 + 魔数校验
# ---------------------------------------------------------------------------
def _is_image_bytes(data: bytes, ext: str) -> bool:
    if ext == "jpg": return data[:3] == b"\xff\xd8\xff"
    if ext == "png": return data[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == "gif": return data[:6] in (b"GIF87a", b"GIF89a")
    return False


def fetch_topic_pool(topic: str) -> list:
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=categorymembers&gcmtype=file&gcmtitle="
           + urllib.parse.quote(f"Category:{topic}") +
           "&gcmlimit=50&prop=imageinfo&iiprop=url|mime&iiurlwidth=150")  # 内存优化：缩小尺寸
    try:
        req = urllib.request.Request(api, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [img-pool] {topic}: 分类清单获取失败 {e}", file=sys.stderr)
        return []
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime")
        url = info.get("thumburl") or info.get("url")
        if mime in ALLOWED_MIME and url:
            title = (page.get("title", "").replace("File:", "").rsplit(".", 1)[0].replace("_", " "))
            out.append((url, mime, title))
    return out


def pick_and_download_images(n: int, state: dict):
    used = set(state.setdefault("used_image_urls", []))
    topics = IMAGE_TOPICS[:]
    random.shuffle(topics)
    for topic, desc in topics:
        pool = [it for it in fetch_topic_pool(topic) if it[0] not in used]
        if len(pool) < n:
            continue
        random.shuffle(pool)
        images, ok = [], True
        for url, mime, title in pool[:n]:
            try:
                data = http_download(url, timeout=30)
            except Exception as e:
                print(f"  [img] 下载失败 {url[:70]} {e}", file=sys.stderr)
                ok = False
                break
            ext = ALLOWED_MIME[mime]
            if not _is_image_bytes(data, ext):
                print(f"  [img] 内容与格式不符 {url[:70]}", file=sys.stderr)
                ok = False
                break
            ctype = "image/jpeg" if ext == "jpg" else f"image/{ext}"
            images.append((data, f"{uuid.uuid4().hex}.{ext}", ctype, title))
            used.add(url)
        state["used_image_urls"] = sorted(used)
        if ok and len(images) == n:
            return topic, desc, images
        if not ok:
            return None
    return None


def gen_post_from_images(persona: dict, desc: str, images: list) -> str:
    titles = "、".join(t for *_, t in images if t)
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"

    # 【内存优化】最多只取前 3 张图转 Base64 发给视觉模型，防止内存撑爆
    vlm_images = images[:3]

    out = llm_vision_generate(
        [(base64.b64encode(d).decode(), ct) for d, _, ct, _ in vlm_images],
        f"这是我即将发布的 {len(images)} 张照片（此处展示前 {len(vlm_images)} 张）。{lang_req} 请以一个年轻网友的口吻写一条 30~120 字帖子正文，"
        f"像描述自己亲眼所见一样自然，口语化，符合你（{persona['personality']}）的性格，只输出正文。")
    if not out:
        out = llm_generate(
            f"你是社区用户「{persona['nickname']}」（{persona['nationality']}人，性格：{persona['personality']}，人设：{persona.get('bio', '')}）。"
            f"{lang_req} 你刚拍了 {len(images)} 张照片准备发帖，主题：{desc}；画面内容提示：{titles or '无'}。"
            f"请写一条 30~120 字帖子正文配这些图，口语化，只输出正文。")
    out = _clean_llm_text(out or "").replace("\n", "")
    if len(out) < 6 or out.startswith("{"):
        sys.exit(f"[致命] 看图写文连续不合格：{out[:80]!r}")
    return out[:280]


# ---------------------------------------------------------------------------
# 人设 / 文本生成
# ---------------------------------------------------------------------------
NICK_STYLES = [
    {"name": "纯英文短语", "desc": "1~3 个英文单词的小写短语，带一点情绪或状态感",
     "examples": "midnight snacker, lowbattery, softcore dreamer"},
    {"name": "英文名+后缀", "desc": "英文昵称搭配数字、.exe、_、酱、子等后缀",
     "examples": "Cici_04, Kai.exe, Momo酱, Vivi不vivi"},
    {"name": "中英混排", "desc": "中文主体夹一个英文单词，或反过来", "examples": "半糖de拿铁, 阿蕉Banana, 今天also很忙"},
    {"name": "短句状态", "desc": "一句 4~10 字的口语状态或宣言，像签名档",
     "examples": "今天也要早睡, 刚下班别cue我, 在逃打工人"},
    {"name": "食物+身份", "desc": "一种食物搭配一个夸张身份或动作",
     "examples": "冰美式续命中, 火锅底料哲学家, 可乐加冰谢谢"},
    {"name": "极简符号", "desc": "2~6 字符的极简组合，可含数字、下划线、点、缩写",
     "examples": "404_, nullo, kksk, yyds本ds"},
    {"name": "职业自嘲", "desc": "职业/身份 + 一句自嘲或免责声明", "examples": "产品经理不背锅, 实习僧, 退堂鼓十级"},
    {"name": "新文艺意象", "desc": "两个字的冷意象组合，要新不要老气", "examples": "屿鹿, 雾岛听风, 拾光者, 盐系黄昏"},
    {"name": "无厘头组合", "desc": "地点/容器 + 动物或物件的荒诞组合",
     "examples": "冰箱里的企鹅, 会飞的拖鞋, 沙发土豆本豆"},
    {"name": "拼音梗", "desc": "拼音缩写或谐音梗，懂自懂", "examples": "xswl本人, 栓Q家族, 芭比Q了, 泰酷辣选手"},
]


def _normalize_nick(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _nick_acceptable(cand: str, used_norm: set) -> bool:
    if not re.fullmatch(r"[\w\u4e00-\u9fff·\-_.\s]{2,16}", cand):
        return False
    n = _normalize_nick(cand)
    if len(n) < 2:
        return False
    if any(b in cand for b in ("用户", "测试", "管理员", "{", "}")):
        return False
    for u in used_norm:
        if n == u:
            return False
        if len(u) >= 3 and (u in n or n in u):
            return False
    return True


def gen_persona(idx: int, used_nicks: list) -> dict:
    # 1. 随机分配国籍与语言
    nat = random.choice(NATIONALITIES)
    used_norm = {_normalize_nick(n) for n in used_nicks if n}
    nick = ""

    for _ in range(5):
        style = random.choice(NICK_STYLES)
        used_show = "、".join(sorted(used_norm)[-40:]) or "（暂无）"
        raw = _clean_llm_text(llm_generate(
            f"你是一个活跃在社交网络的年轻用户，国籍是【{nat['country']}】，主要使用【{nat['prompt_lang']}】。\n"
            f"请给自己取一个符合该国文化背景的网名，必须使用【{style['name']}】风格：{style['desc']}\n"
            f"语气示例：{style['examples']}\n"
            f"硬性要求：\n"
            f"1. 长度 2~16 字符；必须主要使用 {nat['prompt_lang']}。\n"
            f"2. 不得与以下已有网名重复或同构：{used_show}\n"
            f"3. 只输出名字本身，不要引号、结尾标点、解释或 JSON。"))
        cand = raw.strip()[:16]
        if _nick_acceptable(cand, used_norm):
            nick = cand
            break

    if not nick:
        nick = f"BoUser{idx:03d}"
        while not _nick_acceptable(nick, used_norm):
            nick = f"BoUser{idx:03d}-{random.randint(10, 99)}"

    # 2. 生成简介与性格标签
    bio, personality = "", ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"网名「{nick}」，国籍【{nat['country']}】。请写一句 10~25 字的 {nat['prompt_lang']} 个人简介（Bio）。\n"
            f"同时，请用 2~4 个词定义他/她的核心性格（如：热情/毒舌/高冷/幽默/社恐/话痨）。\n"
            f"格式要求：严格以 JSON 格式返回，如：{{\"bio\": \"简介内容\", \"personality\": \"性格词\"}}"))
        try:
            parsed = json.loads(raw)
            bio = parsed.get("bio", "")[:50]
            personality = parsed.get("personality", "普通")
            if bio: break
        except Exception:
            if 2 <= len(raw.strip()) <= 60:
                bio = raw.strip()[:50]
                personality = "随性"
                break

    if not bio:
        bio = f"{nat['prompt_lang']} user"
        personality = "普通"

    # 3. 头像关键词
    avatar_desc = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"网名「{nick}」（{nat['country']}人，{bio}）需要一张匹配其意象的网络头像。\n"
            f"请提取最具象的意象，翻译成 1~4 个英文图片搜索关键词（逗号分隔）。\n"
            f"只输出关键词本身（纯英文小写单词与逗号），不要任何其他内容。"))
        if re.fullmatch(r"[a-z0-9 ,\-]{2,60}", raw.strip()):
            avatar_desc = raw.strip()
            break

    return {
        "nickname": nick, "bio": bio, "avatar_desc": avatar_desc,
        "nationality": nat["country"], "language": nat["language"],
        "lang_code": nat["lang_code"], "prompt_lang": nat["prompt_lang"],
        "personality": personality,
        "interests": random.sample(list(INTEREST_KEYWORDS), k=random.randint(2, 4)),
    }


def gen_text(kind: str, persona: dict, history: list | None = None) -> str:
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"
    if kind == "post":
        if history:
            p = (
                        f"以下是社区用户「{persona['nickname']}」（{persona['nationality']}人，性格：{persona['personality']}，人设：{persona.get('bio', '')}）的历史帖子：\n"
                        + "\n".join(f"- {t}" for t in history) +
                        f"\n{lang_req} 请综合这些历史帖子体现的性格与文风，以同一个人格口吻写一条新的 50~120 字动态，不要重复历史内容，不要话题标签，只输出正文。")
        else:
            p = (
                f"你扮演社区用户「{persona['nickname']}」（{persona['nationality']}人，性格：{persona['personality']}，人设：{persona.get('bio', '')}）。"
                f"{lang_req} 以他/她的口吻发一条社区动态，50~120字，口语化，不要话题标签，只输出正文。")
    else:
        stance = persona.get("interaction_stance", "neutral")
        stance_prompt = {
            "supportive": "这次更倾向真诚支持、接住对方的话题，可自然提到你们过去的互动。",
            "gentle_disagree": "这次可以礼貌表达不同看法，但要具体、克制，绝不嘲讽、人身攻击或挑衅。",
            "neutral": "保持自然交流，不必刻意热络，也不要假装陌生。",
        }.get(stance, "保持自然交流。")
        relationship = persona.get("relationship_context", "")
        p = (f"你是社区用户「{persona['nickname']}」（性格：{persona['personality']}）。"
             f"{lang_req} {relationship}\n{stance_prompt}\n"
             f"请针对下面这条帖子写一条 10~40 字的评论，符合你的性格，可以带点个人经验：\n"
             f"{persona.get('target', '')}\n只输出评论。")

    out = ""
    for _ in range(3):
        out = _clean_llm_text(llm_generate(p)).replace("\n", "")
        min_len = 10 if kind == "post" else 2
        if len(out) >= min_len and not out.startswith("{") and "```" not in out:
            return out[:280]
    sys.exit(f"[致命] {kind} 内容生成连续不合格：{out[:80]!r}")


def fetch_post_history(acc: dict, limit: int = 8) -> list:
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    posts = (r or {}).get("data") or []
    return [p.get("text", "") for p in posts if isinstance(p, dict) and p.get("text")][-limit:]


def fetch_latest_posts(acc: dict, limit: int = 15) -> list:  # 内存优化：降低 limit
    r = http_json("GET", "/posts/getAllPosts", params={"page": 1, "size": limit, "account": acc["account"]},
                  token=acc["token"])
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 本地浏览决策与 Bowall 浏览/停留数据上报
# ---------------------------------------------------------------------------
def _stable_interest_seed(acc: dict) -> int:
    return sum((idx + 1) * ord(ch) for idx, ch in enumerate(str(acc.get("account") or acc.get("nickname") or "bot")))


def ensure_agent_interests(acc: dict, state: dict) -> list:
    """为旧账号补全稳定兴趣标签，并写回状态文件供后续会话复用。"""
    interests = acc.get("interests")
    if not isinstance(interests, list) or not interests:
        cached = state.setdefault("accounts", {}).get(acc.get("nickname"), {})
        interests = cached.get("interests") if isinstance(cached, dict) else None
    if not isinstance(interests, list) or not interests:
        rng = random.Random(_stable_interest_seed(acc))
        interests = rng.sample(list(INTEREST_KEYWORDS), k=rng.randint(2, 4))
    interests = [str(tag) for tag in interests if tag in INTEREST_KEYWORDS][:4]
    if not interests:
        interests = ["life", "travel"]
    acc["interests"] = interests
    with state_lock:
        state.setdefault("accounts", {}).setdefault(acc["nickname"], {})["interests"] = interests
    return interests


def estimate_expected_dwell_seconds(post: dict) -> float:
    """与后端质量统计一致的内容时长基线：文字 + 图片，限制为 3~90 秒。"""
    text = str(post.get("text") or "")
    images = post.get("images") if isinstance(post.get("images"), list) else []
    return max(3.0, min(90.0, 3.0 + (len(text) + 11) // 12 + len(images) * 4))


def local_interest_score(acc: dict, state: dict, post: dict, following: set) -> float:
    """0~1：不调用 LLM 的本地兴趣判断，保留少量随机扰动避免所有 Agent 一致。"""
    text = str(post.get("text") or "")
    lowered = text.lower()
    author = str(post.get("account") or "")
    score = 0.18 + random.uniform(-0.07, 0.07)

    post_lang = detect_lang(text)
    agent_lang = acc.get("lang_code", "unknown")
    score += 0.23 if post_lang == agent_lang or agent_lang == "unknown" else -0.09

    interests = ensure_agent_interests(acc, state)
    matched = 0
    for tag in interests:
        if any(keyword in lowered for keyword in INTEREST_KEYWORDS[tag]):
            matched += 1
    score += min(0.34, matched * 0.15)

    images = post.get("images") if isinstance(post.get("images"), list) else []
    if images and any(tag in interests for tag in ("travel", "food", "photo", "life")):
        score += 0.08

    relation = state.get("relationships", {}).get(acc.get("account"), {}).get(author, {})
    affinity = float(relation.get("affinity", 0) or 0)
    familiarity = float(relation.get("familiarity", 0) or 0)
    score += affinity * 0.20 + familiarity * 0.16
    if author in following:
        score += 0.12

    personality = str(acc.get("personality") or "")
    score += sum(bias for trait, bias in PERSONALITY_DWELL_BIAS.items() if trait in personality) * 0.25
    return _clamp(score, 0.02, 0.98)


def choose_dwell_seconds(acc: dict, post: dict, interest_score: float) -> int:
    """低兴趣通常快速划走，高兴趣可完成阅读；不按真实时间 sleep。"""
    expected = estimate_expected_dwell_seconds(post)
    personality = str(acc.get("personality") or "")
    personality_bias = sum(bias for trait, bias in PERSONALITY_DWELL_BIAS.items() if trait in personality)
    if random.random() > interest_score * 0.70 + 0.20:
        dwell = random.uniform(1.0, min(5.0, expected * 0.35))
    else:
        dwell = expected * (0.38 + interest_score * 1.05 + personality_bias + random.uniform(-0.20, 0.25))
    return int(_clamp(round(dwell), 1, min(300, max(60, expected * 3))))


def report_post_view(acc: dict, post_id: str) -> bool:
    r = http_json("POST", f"/posts/{post_id}/view", token=acc["token"])
    return bool(r) and r.get("code") == 1


def report_post_dwell(acc: dict, post_id: str, session_id: str, dwell_seconds: int) -> bool:
    r = http_json("POST", f"/posts/{post_id}/dwell",
                  {"sessionId": session_id, "seconds": int(dwell_seconds)}, token=acc["token"])
    return bool(r) and r.get("code") == 1


def weighted_sample_without_replacement(items: list, weights: list, count: int) -> list:
    pool = list(zip(items, weights))
    selected = []
    for _ in range(min(count, len(pool))):
        index = random.choices(range(len(pool)), weights=[item[1] for item in pool], k=1)[0]
        selected.append(pool.pop(index)[0])
    return selected


# ---------------------------------------------------------------------------
# 头像：真实网络图片
# ---------------------------------------------------------------------------
def commons_search(query: str, used: set) -> list:
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=search&gsrnamespace=6&gsrlimit=20"
           "&gsrsearch=" + urllib.parse.quote(f"filetype:bitmap {query}") +
           "&prop=imageinfo&iiprop=url|mime&iiurlwidth=200")  # 内存优化
    try:
        req = urllib.request.Request(api, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pool = []
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime")
            url = info.get("thumburl") or info.get("url")
            if mime in ALLOWED_MIME and url and url not in used:
                pool.append((url, ALLOWED_MIME[mime]))
        return pool
    except Exception as e:
        print(f"  [avatar] Commons 搜索失败({query}): {e}", file=sys.stderr)
        return []


def fetch_openverse(keywords: str) -> list:
    api = "https://api.openverse.org/v1/images/?page_size=20&q=" + urllib.parse.quote(keywords)
    try:
        req = urllib.request.Request(api, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for item in data.get("results", []):
            url = item.get("url") or ""
            ext = url.rsplit(".", 1)[-1].lower().split("?")[0] if "." in url else ""
            if ext in ALLOWED_MIME:
                out.append((url, ALLOWED_MIME[ext]))
        return out
    except Exception as e:
        print(f"  [avatar] Openverse 搜索失败({keywords}): {e}", file=sys.stderr)
        return []


def fetch_randomuser_avatar() -> tuple | None:
    try:
        req = urllib.request.Request("https://randomuser.me/api/", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        url = d["results"][0]["picture"]["large"]
        return url, http_download(url, timeout=15)
    except Exception as e:
        print(f"  [avatar] RandomUser 失败: {e}", file=sys.stderr)
        return None


def fetch_avatar(nickname: str, keywords: str, state: dict):
    used = set(state.setdefault("used_avatar_urls", []))
    kw = (keywords or "").strip() or "portrait,face"
    kw_space = kw.replace(",", " ").strip()
    words = kw_space.split()
    kw_first = words[0] if words else "portrait"

    def try_pool(pool, src_name):
        random.shuffle(pool)
        for url, ext in pool[:5]:
            try:
                time.sleep(random.uniform(1.0, 3.0))
                blob = http_download(url, timeout=15)
            except Exception:
                continue
            if _is_image_bytes(blob, ext):
                used.add(url)
                state["used_avatar_urls"] = sorted(used)
                ctype = "image/jpeg" if ext == "jpg" else f"image/{ext}"
                print(f"  [avatar] {nickname}: {src_name} 命中[{kw_space}]")
                return blob, f"{uuid.uuid4().hex}.{ext}", ctype
        return None

    for q in (kw_space, kw_first, "portrait person"):
        pool = commons_search(q, used)
        if pool:
            got = try_pool(pool, "Commons")
            if got: return got

    pool = fetch_openverse(kw_space)
    if pool:
        got = try_pool(pool, "Openverse")
        if got: return got

    for _ in range(3):
        ru = fetch_randomuser_avatar()
        if ru and ru[0] not in used and _is_image_bytes(ru[1], "jpg"):
            used.add(ru[0])
            state["used_avatar_urls"] = sorted(used)
            print(f"  [avatar] {nickname}: RandomUser 真人脸兜底")
            return ru[1], f"{uuid.uuid4().hex}.jpg", "image/jpeg"

    nums = [n for n in range(1, 71) if f"i.pravatar.cc/400?img={n}" not in used]
    random.shuffle(nums)
    for n in nums[:5]:
        url = f"https://i.pravatar.cc/400?img={n}"
        try:
            time.sleep(random.uniform(1.0, 3.0))
            blob = http_download(url, timeout=15)
        except Exception:
            continue
        if _is_image_bytes(blob, "jpg") or _is_image_bytes(blob, "png"):
            ext = "jpg" if _is_image_bytes(blob, "jpg") else "png"
            used.add(url)
            state["used_avatar_urls"] = sorted(used)
            ctype = "image/jpeg" if ext == "jpg" else "image/png"
            print(f"  [avatar] {nickname}: Pravatar 真人脸兜底(#{n})")
            return blob, f"{uuid.uuid4().hex}.{ext}", ctype

    users = GITHUB_AVATARS[:]
    random.shuffle(users)
    for u in users:
        url = f"https://github.com/{u}.png"
        if url in used: continue
        try:
            time.sleep(random.uniform(1.0, 3.0))
            blob = http_download(url, timeout=15)
        except Exception:
            continue
        if _is_image_bytes(blob, "png") or _is_image_bytes(blob, "jpg"):
            ext = "png" if _is_image_bytes(blob, "png") else "jpg"
            used.add(url)
            state["used_avatar_urls"] = sorted(used)
            ctype = "image/png" if ext == "png" else "image/jpeg"
            print(f"  [avatar] {nickname}: GitHub 头像兜底(@{u})")
            return blob, f"{uuid.uuid4().hex}.{ext}", ctype
    return None


# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"accounts": {}}


def save_state(state: dict) -> None:
    with state_lock:
        # 【内存优化】截断列表，防止内存和文件无限膨胀
        if "used_image_urls" in state:
            state["used_image_urls"] = state["used_image_urls"][-3000:]
        if "used_avatar_urls" in state:
            state["used_avatar_urls"] = state["used_avatar_urls"][-1000:]
        if "replied_comment_ids" in state:
            state["replied_comment_ids"] = state["replied_comment_ids"][-2000:]
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 长期关系记忆
# ---------------------------------------------------------------------------
RELATION_MAX_PEERS = 120


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _relationship_bucket(affinity: float, familiarity: float) -> str:
    if familiarity >= 0.75 and affinity >= 0.35: return "熟悉的朋友"
    if familiarity >= 0.45 and affinity <= -0.25: return "熟悉但意见不太一致的人"
    if affinity >= 0.35: return "印象不错的关注对象"
    if affinity <= -0.35: return "观点常有分歧的对象"
    if familiarity >= 0.35: return "有过几次互动的熟人"
    return "关注过但还不熟的人"


def _display_name_for(state: dict, account: str, fallback: str = "对方") -> str:
    for nickname, item in state.get("accounts", {}).items():
        if isinstance(item, dict) and item.get("account") == account:
            return str(item.get("nickname") or nickname or fallback)
    return fallback


def _ensure_relation(state: dict, source: str, target: str, target_name: str) -> dict:
    relationships = state.setdefault("relationships", {})
    source_map = relationships.setdefault(source, {})
    relation = source_map.setdefault(target, {
        "name": target_name or "对方", "affinity": 0.0, "familiarity": 0.0,
        "interactions": 0, "positive_interactions": 0, "disagreements": 0,
        "last_event": "尚未互动", "last_topic": "", "updated_at": 0,
    })
    if target_name: relation["name"] = target_name
    return relation


def relationship_context(state: dict, source: str, target: str, target_name: str) -> str:
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    familiarity = float(relation.get("familiarity", 0))
    name = relation.get("name") or target_name or "对方"
    bucket = _relationship_bucket(affinity, familiarity)
    last_topic = relation.get("last_topic") or "没有特别记忆"
    return (f"关系记忆：这是「{name}」。你们过去互动过 {relation.get('interactions', 0)} 次；"
            f"你对 TA 的好感为 {affinity:.2f}，熟悉度为 {familiarity:.2f}，目前是“{bucket}”。"
            f"最近一次互动：{relation.get('last_event', '尚未互动')}；关联话题：{last_topic}。请延续这段关系的语气。")


def choose_interaction_stance(state: dict, source: str, target: str, target_name: str) -> str:
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    if affinity <= -0.25 and random.random() < 0.55: return "gentle_disagree"
    if affinity >= 0.25 and random.random() < 0.75: return "supportive"
    return "neutral"


def record_relationship(state: dict, source: str, target: str, target_name: str, event: str, stance: str = "neutral",
                        topic: str = "") -> None:
    effects = {"like": (0.025, 0.035), "comment": (0.07, 0.12), "reply": (0.11, 0.16)}
    affinity_delta, familiarity_delta = effects.get(event, (0.02, 0.03))
    if stance == "gentle_disagree":
        affinity_delta = -0.06 if event == "comment" else -0.025
    elif stance == "supportive":
        affinity_delta += 0.04

    with state_lock:
        outgoing = _ensure_relation(state, source, target, target_name)
        outgoing["affinity"] = round(_clamp(float(outgoing["affinity"]) + affinity_delta, -1, 1), 3)
        outgoing["familiarity"] = round(_clamp(float(outgoing["familiarity"]) + familiarity_delta, 0, 1), 3)
        outgoing["interactions"] = int(outgoing["interactions"]) + 1
        outgoing["positive_interactions"] = int(outgoing["positive_interactions"]) + (stance != "gentle_disagree")
        outgoing["disagreements"] = int(outgoing["disagreements"]) + (stance == "gentle_disagree")
        outgoing["last_event"] = {"like": "点赞了对方的动态", "comment": "评论了对方的动态",
                                  "reply": "回复了对方的评论"}.get(event, "产生了互动")
        outgoing["last_topic"] = topic[:80]
        outgoing["updated_at"] = int(time.time())

        reverse_name = _display_name_for(state, source, "对方")
        incoming = _ensure_relation(state, target, source, reverse_name)
        incoming_delta = affinity_delta * (0.7 if stance != "gentle_disagree" else 0.5)
        incoming["affinity"] = round(_clamp(float(incoming["affinity"]) + incoming_delta, -1, 1), 3)
        incoming["familiarity"] = round(_clamp(float(incoming["familiarity"]) + familiarity_delta * 0.75, 0, 1), 3)
        incoming["interactions"] = int(incoming["interactions"]) + 1
        incoming["positive_interactions"] = int(incoming["positive_interactions"]) + (stance != "gentle_disagree")
        incoming["disagreements"] = int(incoming["disagreements"]) + (stance == "gentle_disagree")
        incoming["last_event"] = {"like": "对方点赞了我的动态", "comment": "对方评论了我的动态",
                                  "reply": "对方回复了我的评论"}.get(event, "对方与我互动")
        incoming["last_topic"] = topic[:80]
        incoming["updated_at"] = int(time.time())

        for relations in state.get("relationships", {}).values():
            if len(relations) > RELATION_MAX_PEERS:
                oldest = sorted(relations, key=lambda key: relations[key].get("updated_at", 0))
                for account_id in oldest[:-RELATION_MAX_PEERS]:
                    relations.pop(account_id, None)


# ---------------------------------------------------------------------------
# 账号：登录(自动注册) / 资料完善
# ---------------------------------------------------------------------------
def _verify_token(account: str, token: str) -> bool:
    r = http_json("GET", "/user/getUser", params={"account": account}, token=token)
    d = r.get("data") if isinstance(r, dict) and isinstance(r.get("data"), dict) else {}
    return bool(r) and r.get("code") == 1 and d.get("account") == account


def prune_deleted_accounts(state: dict) -> int:
    pool = state.setdefault("accounts", {})
    deleted = []
    for nickname, account in list(pool.items()):
        account_id = account.get("account") if isinstance(account, dict) else None
        token = account.get("token") if isinstance(account, dict) else None
        if not account_id or not token:
            deleted.append(nickname)
            continue
        response = http_json("GET", "/user/getUser", params={"account": account_id}, token=token)
        if isinstance(response, dict) and response.get("code") == 0 and "不存在" in str(response.get("msg", "")):
            deleted.append(nickname)
    for nickname in deleted:
        pool.pop(nickname, None)
    if deleted:
        save_state(state)
        print(f"[pool] 已清理 {len(deleted)} 个后端不存在的历史账号", file=sys.stderr)
    return len(deleted)


def login_agent(state: dict, nickname: str, dry_run: bool):
    account = state["accounts"].get(nickname)
    if account and account.get("token"):
        if dry_run or _verify_token(account["account"], account["token"]):
            return account
        print(f"  [login] {nickname}: 缓存 token 失效，重新登录…", file=sys.stderr)
    phone = "199" + "".join(random.choices("0123456789", k=8))
    code = "".join(random.choices("0123456789", k=6))
    if dry_run:
        print(f"  [dry] POST /user/login phone={phone}")
        return {"phone": phone, "account": "DRY-" + uuid.uuid4().hex[:8], "token": "dry-token", "nickname": nickname}
    r = http_json("POST", "/user/login", {"phone": phone, "code": code, "randomNum": code})
    data = (r or {}).get("data")
    data = data if isinstance(data, dict) else {}
    token = data.get("token")
    user = data.get("user") or {}
    if not token:
        print(f"  [login] 失败: {r}", file=sys.stderr)
        return None
    acc = {"phone": phone, "account": user.get("account"), "token": token, "nickname": nickname}
    state["accounts"][nickname] = acc
    save_state(state)
    return acc


def setup_profile(acc: dict, persona: dict, state: dict, dry_run: bool) -> bool:
    if dry_run:
        print(f"[dry] {acc['nickname']}: GET getUser -> PUT /user -> POST /user/avatar")
        return True
    r = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
    _u = (r or {}).get("data")
    user = _u if isinstance(_u, dict) else {}
    if not user.get("account"):
        sys.exit(f"[致命] {acc['nickname']} 获取用户信息失败，程序终止")

    nickname = str(persona.get("nickname") or acc.get("nickname") or "").strip()
    if not nickname:
        nickname = f"BoUser-{user['account'][:8]}"
        print(f"  [profile] {acc.get('nickname', user['account'])}: 昵称为空，使用兜底昵称 {nickname}", file=sys.stderr)

    def put_profile(av):
        payload = {"account": user["account"], "name": nickname, "sign": persona["bio"], "phone": user.get("phone"),
                   "avatar": av}
        return bool(http_json("PUT", "/user", payload, token=acc["token"], raise_on_error=True))

    avatar_url = user.get("avatar")
    if not avatar_url:
        img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""), state)
        if not img:
            sys.exit(f"[致命] {acc['nickname']} 头像下载失败（所有源不可用），程序终止")
        data, fname, ctype = img
        up = http_multipart("POST", "/user/avatar", fields={"account": acc["account"]}, file_field="avatar",
                            filename=fname, file_bytes=data, content_type=ctype, token=acc["token"])
        avatar_data = (up or {}).get("data")
        new_avatar = avatar_data.get("avatar") if isinstance(avatar_data, dict) else None
        if not new_avatar:
            sys.exit(f"[致命] {acc['nickname']} 头像上传失败，程序终止")
        avatar_url = new_avatar
        state.setdefault("avatars", {})[persona["nickname"]] = new_avatar
        print(f"[avatar] {acc['nickname']}: 上传成功 {new_avatar}")

    try:
        if not put_profile(avatar_url):
            sys.exit(f"[致命] {acc['nickname']} PUT /user 失败，程序终止")
    except ApiError as e:
        sys.exit(f"[致命] {acc['nickname']} 更新资料失败: {e}")

    check = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
    _g = (check or {}).get("data")
    got = _g if isinstance(_g, dict) else {}
    if got.get("name") != nickname:
        sys.exit(f"[致命] {acc['nickname']} 回读校验失败 name={got.get('name')!r}")
    print(f"[profile] {acc['nickname']}: OK name='{got.get('name')}' avatar={got.get('avatar') or '无'}")
    return True


# ---------------------------------------------------------------------------
# 社交动作
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 关注功能 API 层
# ---------------------------------------------------------------------------
def check_is_following(my_acc: str, target_acc: str, token: str) -> bool:
    """检查是否已经关注对方 (GET /fans/isfan)"""
    r = http_json("GET", "/fans/isfan", params={"account": target_acc, "fansAccount": my_acc}, token=token)
    if r and r.get("code") == 1:
        data = r.get("data")
        # 兼容后端返回 null 或 {} 的情况
        if isinstance(data, dict) and data: return True
        if isinstance(data, str) and data: return True
    return False

def toggle_follow(my_acc: str, target_acc: str, token: str) -> bool:
    """关注/取关切换 (POST /user/add)"""
    r = http_json("POST", "/user/add", {"account": target_acc, "fansAccount": my_acc}, token=token)
    return bool(r) and r.get("code") == 1

def fetch_post_comments(post_id: str, acc: dict) -> list:
    r = http_json("GET", "/comments/getComments", params={"postId": str(post_id), "page": 1, "size": 20},
                  token=acc["token"])
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


def check_and_reply_interactions(acc: dict, state: dict, dry_run: bool):
    nick = acc["nickname"]
    print(f"🔔 [{nick}] 正在检查是否有新互动...")
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    my_posts = (r or {}).get("data") or []
    if not my_posts:
        return

    replied_ids = set(state.setdefault("replied_comment_ids", []))
    new_replies = []

    for post in my_posts[:5]:
        pid = post.get("id")
        if not pid: continue
        comments = fetch_post_comments(str(pid), acc)
        for cmt in comments:
            cmt_id = str(cmt.get("id") or cmt.get("commentId") or "")
            cmt_account = cmt.get("account")
            cmt_text = str(cmt.get("comments") or cmt.get("content") or cmt.get("text") or "")
            if cmt_account and cmt_account != acc["account"] and cmt_id not in replied_ids and not cmt.get("parentId"):
                new_replies.append({"post_id": str(pid), "comment_id": cmt_id, "text": cmt_text, "author": cmt_account})

    if not new_replies:
        print(f"🔕 [{nick}] 没有新的未回复互动。")
        return

    personality = acc.get("personality", "普通")
    reply_chance = 0.9 if "热情" in personality or "话痨" in personality else 0.3 if "高冷" in personality or "社恐" in personality else 0.6

    for item in new_replies:
        time.sleep(random.uniform(1.0, 3.0))
        if random.random() > reply_chance:
            print(f"🙅 [{nick}] 性格使然，决定忽略评论: '{item['text'][:20]}...'")
            continue

        # 【已修复 f-string 语法错误】
        print(f"💬 [{nick}] 发现新评论，准备以【{personality}】性格回复: '{item['text'][:20]}...'")
        if dry_run:
            print(f"[dry] [{nick}] 回复评论 {item['comment_id'][:8]}")
            continue

        commenter_name = _display_name_for(state, item["author"], "这位评论者")
        stance = choose_interaction_stance(state, acc["account"], item["author"], commenter_name)
        reply_text = gen_text("comment", {
            **acc, "target": item["text"], "interaction_stance": stance,
            "relationship_context": relationship_context(state, acc["account"], item["author"], commenter_name),
        })

        r = http_json("POST", "/comments/post",
                      {"postsId": item["post_id"], "account": acc["account"], "comments": reply_text,
                       "parentId": item["comment_id"], "replyToAccount": item["author"]}, token=acc["token"])
        if r and r.get("code") == 1:
            print(f"✅ [{nick}] 回复成功: '{reply_text[:30]}...'")
            with state_lock:
                state.setdefault("replied_comment_ids", []).append(item["comment_id"])
            record_relationship(state, acc["account"], item["author"], commenter_name, "reply", stance, item["text"])
            save_state(state)
        else:
            print(f"❌ [{nick}] 回复失败")


def create_post(acc: dict, text: str, dry_run: bool):
    if dry_run:
        print(f"[dry] {acc['nickname']} 发帖: {text[:50]}")
        return "dry-post-id"
    r = http_json("POST", "/posts/post", {"account": acc["account"], "text": text}, token=acc["token"])
    if r and r.get("code") == 1:
        pid = r.get("data")
        print(f"[post] {acc['nickname']}: OK id={pid} - {text[:30]}")
        return pid
    print(f"[post] {acc['nickname']}: FAIL - {text[:30]}")
    return None


def create_post_with_images(acc: dict, text: str, images: list, dry_run: bool):
    pid = create_post(acc, text, dry_run)
    if not pid: return None
    for data, fname, ctype, _t in images:
        up = http_multipart("POST", "/image/post", fields={"account": acc["account"], "postId": pid},
                            file_field="images", filename=fname, file_bytes=data, content_type=ctype,
                            token=acc["token"])
        if not (up and up.get("code") == 1):
            print(f"[post] 图片上传失败，回滚删帖 {pid[:8]}", file=sys.stderr)
            http_json("DELETE", f"/posts/delete/{pid}", params={"account": acc["account"]}, token=acc["token"])
            return None
    if images:
        print(f"[post] {acc['nickname']}: {len(images)} 张图片绑定成功")
    return pid


def comment_post(acc: dict, post_id: str, text: str, target_account: str, dry_run: bool):
    if dry_run:
        print(f"[dry] {acc['nickname']} 评论 {post_id[:8]}: {text[:40]}")
        return True
    r = http_json("POST", "/comments/post", {"postsId": post_id, "account": acc["account"], "comments": text,
                                             "parentId": "", "replyToAccount": target_account or ""},
                  token=acc["token"])
    ok = bool(r) and r.get("code") == 1
    print(f"[comment] {acc['nickname']}: {'OK' if ok else 'FAIL'} - {text[:20]}")
    return ok


def like_post(acc: dict, post_id: str, dry_run: bool):
    if dry_run:
        print(f"[dry] {acc['nickname']} 点赞 {post_id[:8]}")
        return True
    r = http_json("POST", "/like", {"account": acc["account"], "postId": post_id}, token=acc["token"])
    ok = bool(r) and r.get("code") == 1
    print(f"[like] {acc['nickname']}: {'OK' if ok else 'FAIL'} {post_id[:8]}")
    return ok


# ---------------------------------------------------------------------------
# 发帖与用户会话（流水席核心）
# ---------------------------------------------------------------------------
def publish_a_post(acc: dict, state: dict):
    n_img = random.randint(0, 9)
    if n_img == 0:
        history = fetch_post_history(acc)
        content = gen_text("post", acc, history=history)
        print(f"[post-plan] {acc['nickname']}: 纯文字帖（综合 {len(history)} 条历史性格）")
        imgs = []
    else:
        with state_lock:
            got = pick_and_download_images(n_img, state)
        if not got:
            print(f"[post] {acc['nickname']}: 图片下载失败/库存不足，放弃本条发帖", file=sys.stderr)
            save_state(state)
            return None
        _topic, desc, imgs = got
        content = gen_post_from_images(acc, desc, imgs)
        print(f"[post-plan] {acc['nickname']}: {n_img} 张图 主题='{desc}'")
    pid = create_post_with_images(acc, content, imgs, False)
    save_state(state)
    return pid


def simulate_user_session(acc: dict, state: dict, dry_run: bool):
    nick = acc["nickname"]
    lang_code = acc.get("lang_code", "unknown")
    print(f"📱 [{nick}] ({acc.get('nationality')}) 上线了，开始刷动态…")

    if dry_run:
        print(f"[dry] [{nick}] 浏览(偏好{acc.get('language')}) -> 随机互动 -> 发帖 -> 回访 -> 下线")
        return

    if not state["accounts"].get(nick, {}).get("profile_done"):
        time.sleep(random.uniform(3.0, 15.0))
        throttle_avatar()
        persona = {"nickname": nick, "bio": acc.get("bio", ""), "avatar_desc": acc.get("avatar_desc", "")}
        setup_profile(acc, persona, state, False)
        state["accounts"][nick]["profile_done"] = True
        state["accounts"][nick]["bio"] = acc.get("bio", "")
        state["accounts"][nick]["avatar_desc"] = acc.get("avatar_desc", "")
        state["accounts"][nick]["personality"] = acc.get("personality", "普通")
        state["accounts"][nick]["nationality"] = acc.get("nationality", "")
        state["accounts"][nick]["language"] = acc.get("language", "")
        state["accounts"][nick]["lang_code"] = acc.get("lang_code", "unknown")
        state["accounts"][nick]["prompt_lang"] = acc.get("prompt_lang", "简体中文")
        state["accounts"][nick]["interests"] = ensure_agent_interests(acc, state)
        save_state(state)

    posts = fetch_latest_posts(acc, limit=15)
    if not posts:
        print(f"📱 [{nick}] 广场没帖子，溜了溜了")
        return

    # === 新增：获取本地已关注列表，用于提升权重 ===
    acc_state = state["accounts"].get(nick, {})
    already_following = set(acc_state.get("following", []))

    ensure_agent_interests(acc, state)
    scored_posts = []
    for post in posts:
        pauthor = str(post.get("account") or "")
        if not pauthor or pauthor == acc["account"]:
            continue
        score = local_interest_score(acc, state, post, already_following)
        # 选帖权重只决定“刷到”的可能性；是否真正浏览仍在下方单独决策。
        scored_posts.append((post, max(0.05, score ** 1.6 + random.uniform(0.01, 0.12))))

    browse_count = min(random.randint(3, 8), len(scored_posts))
    browse = weighted_sample_without_replacement(
        [item[0] for item in scored_posts], [item[1] for item in scored_posts], browse_count)
    session_id = uuid.uuid4().hex

    for post in browse:
        pid = post.get("id")
        ptext = post.get("text", "")
        pauthor = post.get("account", "")
        if not pid or pauthor == acc["account"]:
            continue

        author_data = post.get("user") if isinstance(post.get("user"), dict) else {}
        author_name = author_data.get("name") or _display_name_for(state, pauthor, "这位作者")

        interest_score = local_interest_score(acc, state, post, already_following)
        view_probability = _clamp(0.12 + interest_score * 0.82 + random.uniform(-0.10, 0.10), 0.05, 0.98)
        if random.random() > view_probability:
            print(f"[skip] [{nick}] 兴趣 {interest_score:.2f}，未真实浏览 {str(pid)[:8]}")
            continue

        if not report_post_view(acc, str(pid)):
            print(f"[view] [{nick}] 浏览上报失败，跳过互动 {str(pid)[:8]}", file=sys.stderr)
            continue
        dwell_seconds = choose_dwell_seconds(acc, post, interest_score)
        dwell_ok = report_post_dwell(acc, str(pid), session_id, dwell_seconds)
        print(f"[view] [{nick}] 兴趣 {interest_score:.2f}，停留 {dwell_seconds}s，dwell={'OK' if dwell_ok else 'FAIL'}")

        # 浏览行为不按 dwell 时间 sleep；轻量随机停顿仅模拟网络操作节奏。
        time.sleep(random.uniform(0.15, 0.65))

        personality = str(acc.get("personality") or "")
        relation = state.get("relationships", {}).get(acc["account"], {}).get(pauthor, {})
        affinity = float(relation.get("affinity", 0) or 0)
        like_probability = _clamp(SESSION_CFG["like"] * (0.20 + interest_score * 1.45)
                                  + max(0, affinity) * 0.14 + (0.05 if "热情" in personality else 0), 0.01, 0.90)
        read_depth = dwell_seconds / max(1.0, estimate_expected_dwell_seconds(post))
        comment_probability = _clamp(SESSION_CFG["comment"] * (0.12 + interest_score * 1.80)
                                     * _clamp(read_depth, 0.18, 1.25)
                                     + max(0, affinity) * 0.10
                                     + (0.06 if any(word in personality for word in ("话痨", "热情", "幽默")) else 0), 0.005, 0.70)

        if post.get("isLike") == 0 and random.random() < like_probability:
            if like_post(acc, pid, False):
                record_relationship(state, acc["account"], pauthor, author_name, "like", "supportive", ptext)
            time.sleep(random.uniform(0.5, 1.5))

        if random.random() < comment_probability:
            print(f"💬 [{nick}] 看了 '{ptext[:15]}…' 想评论一下")
            stance = choose_interaction_stance(state, acc["account"], pauthor, author_name)
            c = gen_text("comment", {
                **acc, "target": ptext, "interaction_stance": stance,
                "relationship_context": relationship_context(state, acc["account"], pauthor, author_name),
            })
            if comment_post(acc, pid, c, pauthor, False):
                record_relationship(state, acc["account"], pauthor, author_name, "comment", stance, ptext)
            time.sleep(random.uniform(2.0, 4.0))

    if random.random() < SESSION_CFG["post"]:
        print(f"✍️ [{nick}] 突然有了分享欲，准备发帖…")
        publish_a_post(acc, state)
        time.sleep(random.uniform(2.0, 5.0))
        check_and_reply_interactions(acc, state, False)
    else:
        if random.random() < 0.4:
            check_and_reply_interactions(acc, state, False)

    # =====================================================================
    # 🌟 新增：离线前评估关注逻辑 (长期价值 & 短期高情绪)
    # =====================================================================
    print(f"🔍 [{nick}] 评估今日互动对象，决定是否关注...")
    my_relations = state.get("relationships", {}).get(acc["account"], {})
    followed_count = 0

    for target_acc, relation in my_relations.items():
        if not target_acc or target_acc == acc["account"]: continue

        affinity = float(relation.get("affinity", 0))
        familiarity = float(relation.get("familiarity", 0))

        # 触发条件：
        # 1. 长期价值：熟悉度 >= 0.4 且 好感度 >= 0.35 (经常看到且印象不错)
        # 2. 短期高情绪：好感度极高 >= 0.60 (单次互动极度共鸣，相见恨晚)
        should_follow = (familiarity >= 0.4 and affinity >= 0.35) or (affinity >= 0.60)

        if should_follow and target_acc not in already_following:
            target_name = relation.get("name", "对方")
            print(f"✨ [{nick}] 觉得 {target_name} 很有共鸣，决定关注！(好感:{affinity:.2f}, 熟悉:{familiarity:.2f})")

            if not dry_run:
                # 防 toggle 误伤：先查 DB 是否已关注
                is_fan = check_is_following(acc["account"], target_acc, acc["token"])
                if not is_fan:
                    if toggle_follow(acc["account"], target_acc, acc["token"]):
                        print(f"✅ [{nick}] 成功关注 {target_name}")
                        already_following.add(target_acc)
                        followed_count += 1
                    else:
                        print(f"❌ [{nick}] 关注 {target_name} 失败")
                else:
                    # DB 已关注但本地状态未同步，直接同步
                    already_following.add(target_acc)
            else:
                already_following.add(target_acc)

    if followed_count > 0:
        print(f"🌟 [{nick}] 本次共新关注了 {followed_count} 人。")

    acc_state["following"] = list(already_following)
    # =====================================================================

    save_state(state)
    print(f"👋 [{nick}] 刷累了，下线休息。")

    # 【内存优化】强制垃圾回收，释放图片 bytes 和 Base64 字符串
    gc.collect()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="AI 社区模拟机器人（流水席版）")
    ap.add_argument("--agents", type=int, default=300, help="账号池总数")
    ap.add_argument("--concurrent", type=int, default=50, help="同时在线人数 (内存敏感，建议<=10)")
    ap.add_argument("--like-chance", type=float, default=0.40)
    ap.add_argument("--comment-chance", type=float, default=0.15)
    ap.add_argument("--post-chance", type=float, default=0.10)
    ap.add_argument("--no-avatar", action="store_true", help="跳过资料/头像设置")
    ap.add_argument("--interval", type=float, default=0.5, help="备号阶段请求间隔")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    args = ap.parse_args()

    SESSION_CFG.update({"like": args.like_chance, "comment": args.comment_chance, "post": args.post_chance})

    if not LLM_KEY:
        sys.exit("[致命] 必须设置 BOT_LLM_KEY。例: export BOT_LLM_KEY=sk-xxx")
    print(f"[llm] 使用模型 {LLM_MODEL} @ {LLM_URL}")

    state = load_state()

    print(f"=== 阶段一：准备 {args.agents} 个账号（优先复用历史账号池） ===")
    pool = state.setdefault("accounts", {})
    prune_deleted_accounts(state)
    existing = [n for n in pool.keys() if pool[n].get("account")]
    reuse = random.sample(existing, min(args.agents, len(existing))) if existing else []
    need_new = max(0, args.agents - len(reuse))
    print(f"[pool] 后端有效历史账号池 {len(existing)} 个 | 本次复用 {len(reuse)} 个 | 需新注册 {need_new} 个")

    prepared, seen = [], set(reuse)
    for nick in reuse:
        cached = pool[nick]
        acc = login_agent(state, nick, args.dry_run)
        if not acc: continue
        acc["bio"] = cached.get("bio") or state.get("personas", {}).get(nick, "")
        acc["avatar_desc"] = cached.get("avatar_desc", "")
        acc["personality"] = cached.get("personality", "普通")
        acc["nationality"] = cached.get("nationality", "")
        acc["language"] = cached.get("language", "")
        acc["lang_code"] = cached.get("lang_code", "unknown")
        acc["prompt_lang"] = cached.get("prompt_lang", acc.get("language") or "简体中文")
        acc["interests"] = cached.get("interests", [])
        ensure_agent_interests(acc, state)
        prepared.append(acc)
        time.sleep(args.interval)

    for i in range(need_new):
        used_pool = list(seen) + [p["nickname"] for p in prepared] + list(pool.keys())
        persona = gen_persona(i + 1, used_pool)
        if persona["nickname"] in seen: continue
        seen.add(persona["nickname"])
        state.setdefault("personas", {})[persona["nickname"]] = persona["bio"]
        print(f"[persona] 新注册 {persona['nickname']}：{persona['bio']}")
        acc = login_agent(state, persona["nickname"], args.dry_run)
        if not acc: continue
        acc["bio"] = persona["bio"]
        acc["avatar_desc"] = persona.get("avatar_desc", "")
        acc.update({key: persona.get(key) for key in ("personality", "nationality", "language", "lang_code", "prompt_lang", "interests")})
        ensure_agent_interests(acc, state)
        prepared.append(acc)
        time.sleep(args.interval)
    save_state(state)
    print(f"=== 账号就绪：{len(prepared)} 个（老号 {len(reuse)} + 新号 {len(prepared) - len(reuse)}） ===")

    print(f"\n=== 阶段二：流水席模拟（同时在线 {args.concurrent} 人） ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrent) as ex:
        futures = [ex.submit(simulate_user_session, acc, state, args.dry_run) for acc in prepared]
        concurrent.futures.wait(futures)

    save_state(state)
    print(f"\n🎉 完成：{len(prepared)} 个账号轮流刷完社区。状态缓存: {STATE_FILE}")


if __name__ == "__main__":
    main()
