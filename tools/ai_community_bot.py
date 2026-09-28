#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 社区模拟机器人（流水席版 · 完整整合）

特性：
  1. 所有内容（网名/简介/帖子/评论）由 LLM 实时生成，网名风格对标小红书/X；
  2. 注册时自动编网名 + 从网络抓真实图片上传头像（头像失败=终止程序）；
  3. 发帖随机 0~9 张图：无图=综合历史性格发帖，有图=看图写文；
     同帖图片同风格、跨帖不重复；图片下载失败=放弃该帖；
  4. 流水席模型：账号池 N 人（默认100），同时在线 M 人（默认20），
     每人"上线刷一会 -> 随机点赞/评论/发帖 -> 下线"，线程池自动补位；
  5. 多线程安全：LLM 信号量限流 + 状态文件锁 + 点赞防 toggle（isLike 判断）。

依赖：仅 Python 标准库。

用法：
  export BOT_LLM_KEY=sk-xxxx
  export BOWALL_BASE=http://localhost:8080
  python tools/ai_community_bot.py --agents 100 --concurrent 20
  python tools/ai_community_bot.py --dry-run --agents 5   # 只看计划
"""

import argparse
import base64
import concurrent.futures
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

# 新增：国籍与语言池 (可根据需要扩展)
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
    if re.search(r'[àâäéèêëïîôùûüÿçœæñ]', text, re.I): return "es" # 简化西/法识别
    return "en" # 默认兜底为英文


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
        # DeepSeek 连续返回空值或不合规文本时，仍生成稳定、可读且不重复的昵称。
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
            # 尝试解析 JSON，如果 LLM 带了 markdown 代码块，_clean_llm_text 已处理大部分
            import json
            parsed = json.loads(raw)
            bio = parsed.get("bio", "")[:50]
            personality = parsed.get("personality", "普通")
            if bio: break
        except Exception:
            # 兜底：如果不是 JSON，强行截取
            if 2 <= len(raw.strip()) <= 60:
                bio = raw.strip()[:50]
                personality = "随性"
                break

    if not bio:
        bio = f"{nat['prompt_lang']} user"
        personality = "普通"

    # 3. 头像关键词 (保持原逻辑，但提示词加入国籍背景)
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
        "personality": personality
    }

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")

# 并发控制：LLM 限流信号量 + 状态文件锁
llm_semaphore = threading.Semaphore(3)
state_lock = threading.Lock()
# 头像下载全局节流：同一时刻仅 1 个下载，且两次下载最小间隔 AVATAR_MIN_GAP 秒
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


# ---------------------------------------------------------------------------
# 基础网络层
# ---------------------------------------------------------------------------
def http_download(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_multipart(method: str, path: str, fields: dict, file_field: str,
                   filename: str, file_bytes: bytes, content_type: str, token=None):
    """multipart/form-data 上传（对应后端 @RequestParam MultipartFile）。"""
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
    except Exception as e:  # noqa: BLE001
        print(f"  [upload] {method} {path} -> {e}", file=sys.stderr)
    return None


class ApiError(Exception):
    pass


def http_json(method: str, path: str, body=None, token=None, params=None,
              raise_on_error=False):
    """R 结构：code==1 成功；code==0 失败。"""
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
    except Exception as e:  # noqa: BLE001
        print(f"  [http] {method} {path} -> {e}", file=sys.stderr)
        return None
    if isinstance(r, dict) and r.get("code") not in (1, None):
        msg = r.get("msg")
        if raise_on_error:
            raise ApiError(f"{method} {path}: {msg}")
        print(f"  [api] {method} {path} -> code={r.get('code')} msg={msg}",
              file=sys.stderr)
    return r


# ---------------------------------------------------------------------------
# LLM 接入层（OpenAI 兼容协议，带限流信号量 + 429 退避）
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
            except Exception as e:  # noqa: BLE001
                print(f"  [llm] 第{i + 1}次失败: {e}", file=sys.stderr)
                time.sleep(2 + i)
    sys.exit("[致命] LLM 调用连续失败，已中止（无兜底模板，不灌假数据）。")


def llm_vision_generate(items: list, prompt: str):
    """可选视觉模型：items = [(b64, content_type), ...]"""
    if not (VLM_URL and VLM_KEY):
        return None
    content = [{"type": "text", "text": prompt}]
    for b64, ctype in items[:9]:
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{ctype};base64,{b64}"}})
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
    except Exception as e:  # noqa: BLE001
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
    if ext == "jpg":
        return data[:3] == b"\xff\xd8\xff"
    if ext == "png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == "gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    return False


def fetch_topic_pool(topic: str) -> list:
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=categorymembers&gcmtype=file&gcmtitle="
           + urllib.parse.quote(f"Category:{topic}") +
           "&gcmlimit=50&prop=imageinfo&iiprop=url|mime&iiurlwidth=300")
    try:
        req = urllib.request.Request(api, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  [img-pool] {topic}: 分类清单获取失败 {e}", file=sys.stderr)
        return []
    out = []
    for page in (data.get("query", {}).get("pages", {}) or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        mime = info.get("mime")
        url = info.get("thumburl") or info.get("url")
        if mime in ALLOWED_MIME and url:
            title = (page.get("title", "").replace("File:", "")
                     .rsplit(".", 1)[0].replace("_", " "))
            out.append((url, mime, title))
    return out


def pick_and_download_images(n: int, state: dict):
    """选一个主题下载 n 张同风格、全局不重复图片。
    任一张失败 -> 返回 None（调用方放弃发帖）。调用方需持有/释放 state_lock 自行控制。"""
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
            except Exception as e:  # noqa: BLE001
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
    out = llm_vision_generate(
        [(base64.b64encode(d).decode(), ct) for d, _, ct, _ in images],
        f"这是我即将发布的 {len(images)} 张照片。{lang_req} 请以一个年轻网友的口吻写一条 30~120 字帖子正文，"
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
# 网名风格骰子：每次随机抽一种，强制 LLM 跳出舒适区（覆盖小红书/X 真实生态）
NICK_STYLES = [
    {"name": "纯英文短语", "desc": "1~3 个英文单词的小写短语，带一点情绪或状态感",
     "examples": "midnight snacker, lowbattery, softcore dreamer, not a tourist"},
    {"name": "英文名+后缀", "desc": "英文昵称搭配数字、.exe、_、酱、子等后缀",
     "examples": "Cici_04, Kai.exe, Momo酱, Vivi不vivi, Leo_离线中"},
    {"name": "中英混排", "desc": "中文主体夹一个英文单词，或反过来",
     "examples": "半糖de拿铁, 阿蕉Banana, 今天also很忙, 摸鱼pro Max"},
    {"name": "短句状态", "desc": "一句 4~10 字的口语状态或宣言，像签名档",
     "examples": "今天也要早睡, 刚下班别cue我, 在逃打工人, 别卷了求你"},
    {"name": "食物+身份", "desc": "一种食物搭配一个夸张身份或动作",
     "examples": "冰美式续命中, 火锅底料哲学家, 可乐加冰谢谢, 蛋挞护卫队"},
    {"name": "极简符号", "desc": "2~6 字符的极简组合，可含数字、下划线、点、缩写",
     "examples": "404_, nullo, kksk, yyds本ds, dddd懂自懂"},
    {"name": "职业自嘲", "desc": "职业/身份 + 一句自嘲或免责声明",
     "examples": "产品经理不背锅, 实习僧, 退堂鼓十级, 甲方克星"},
    {"name": "新文艺意象", "desc": "两个字的冷意象组合，要新不要老气",
     "examples": "屿鹿, 雾岛听风, 拾光者, 盐系黄昏"},
    {"name": "无厘头组合", "desc": "地点/容器 + 动物或物件的荒诞组合",
     "examples": "冰箱里的企鹅, 会飞的拖鞋, 沙发土豆本豆, 天花板观察员"},
    {"name": "拼音梗", "desc": "拼音缩写或谐音梗，懂自懂",
     "examples": "xswl本人, 栓Q家族, 芭比Q了, 泰酷辣选手"},
]


def _normalize_nick(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _nick_acceptable(cand: str, used_norm: set) -> bool:
    """格式校验 + 去重 + 防'换汤不换药'（子串/同构拦截）。"""
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
        if len(u) >= 3 and (u in n or n in u):   # 拦截 "香菜末日" vs "香菜末日中"
            return False
    return True


def gen_persona(idx: int, used_nicks: list) -> dict:
    used_norm = {_normalize_nick(n) for n in used_nicks if n}
    nick = ""
    for _ in range(5):
        style = random.choice(NICK_STYLES)
        used_show = "、".join(sorted(used_norm)[-40:]) or "（暂无）"
        raw = _clean_llm_text(llm_generate(
            f"你是一个活跃在小红书 / X(Twitter) 的年轻用户，正在给自己取一个新网名。\n"
            f"本次必须使用【{style['name']}】风格：{style['desc']}\n"
            f"语气示例（仅感受风格，禁止照抄或改一个字照抄）：{style['examples']}\n"
            f"硬性要求：\n"
            f"1. 长度 2~16 字符；允许纯中文 / 纯英文 / 中英混排 / 带数字或 . _ - 空格。\n"
            f"2. 不得与以下已有网名重复或同构（同核心词、同句式、仅改后缀都算重复）：\n"
            f"{used_show}\n"
            f"3. 禁止老气词（清风/明月/岁月静好/宁静致远），禁止含'用户/测试/管理员'。\n"
            f"4. 只输出名字本身，不要引号、结尾标点、解释或 JSON。"))
        cand = raw.strip()[:16]
        if _nick_acceptable(cand, used_norm):
            nick = cand
            break
    if not nick:
        base = _clean_llm_text(llm_generate(
            "随机输出一个 2~6 字中文网名，只输出名字本身。"))[:8]
        nick = base or f"BoUser{idx:03d}"
        if not _nick_acceptable(nick, used_norm):
            nick = f"BoUser{idx:03d}"
        print(f"  [persona] 多次撞名，本地加后缀兜底: {nick}", file=sys.stderr)
    used_norm.add(_normalize_nick(nick))

    bio = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"给网名「{nick}」写一句 10~25 字的个人简介（Bio）。风格参考小红书/X："
            f"状态描述（如'间歇性努力，持续性发呆'）、爱好标签（如'咖啡依赖者 | 周末逃跑计划'）、"
            f"或一句随性吐槽。口语化、有网感，不要像求职简历。只输出简介本身。"))
        if 2 <= len(raw.strip()) <= 60 and "{" not in raw:
            bio = raw.strip()[:50]
            break
    if not bio:
        sys.exit(f"[致命] 「{nick}」的简介生成连续失败（无兜底模板）。")

    avatar_desc = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"网名「{nick}」（简介：{bio}）需要一张匹配其意象的网络头像。\n"
            f"请提取网名中最具象的意象，翻译成 1~4 个英文图片搜索关键词（逗号分隔）。\n"
            f"示例：'在发呆的猫'->cat,sleeping；'半熟芝士'->cheesecake；"
            f"'日落收集者'->sunset；'野生草莓'->strawberry；'赛博菩萨'->cyberpunk,statue。\n"
            f"若网名完全抽象或为英文，则从简介里挑最具象的爱好或物品。\n"
            f"只输出关键词本身（纯英文小写单词与逗号），不要任何其他内容。"))
        raw = raw.strip().lower().strip(",")
        if re.fullmatch(r"[a-z0-9 ,\-]{2,60}", raw):
            avatar_desc = raw
            break
    return {"nickname": nick, "bio": bio, "avatar_desc": avatar_desc}


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
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]},
                  token=acc["token"])
    posts = (r or {}).get("data") or []
    return [p.get("text", "") for p in posts
            if isinstance(p, dict) and p.get("text")][-limit:]


def fetch_latest_posts(acc: dict, limit: int = 30) -> list:
    r = http_json("GET", "/posts/getAllPosts",
                  params={"page": 1, "size": limit, "account": acc["account"]},
                  token=acc["token"])
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 头像：真实网络图片
# ---------------------------------------------------------------------------
def commons_search(query: str, used: set) -> list:
    """Wikimedia Commons 按关键词搜图：返回 [(url, ext), ...]，过滤已用 URL。"""
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json"
           "&generator=search&gsrnamespace=6&gsrlimit=20"
           "&gsrsearch=" + urllib.parse.quote(f"filetype:bitmap {query}") +
           "&prop=imageinfo&iiprop=url|mime&iiurlwidth=200")
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
    except Exception as e:  # noqa: BLE001
        print(f"  [avatar] Commons 搜索失败({query}): {e}", file=sys.stderr)
        return []


def fetch_openverse(keywords: str) -> list:
    """Openverse 官方免 key 搜索 API：返回 [(url, ext), ...]。"""
    api = ("https://api.openverse.org/v1/images/?page_size=20&q="
           + urllib.parse.quote(keywords))
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
    except Exception as e:  # noqa: BLE001
        print(f"  [avatar] Openverse 搜索失败({keywords}): {e}", file=sys.stderr)
        return []


def fetch_randomuser_avatar() -> tuple | None:
    """RandomUser.me 免 key API：返回一张随机真人脸 jpg。(url, bytes)"""
    try:
        req = urllib.request.Request("https://randomuser.me/api/", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        url = d["results"][0]["picture"]["large"]
        return url, http_download(url, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"  [avatar] RandomUser 失败: {e}", file=sys.stderr)
        return None

def fetch_avatar(nickname: str, keywords: str, state: dict):
    """按网名关键词搜真实网图作头像；5 层源逐级兜底，跨账号去重 + 魔数校验。
    源1 Commons(关键词三级降级) -> 源2 Openverse(关键词) ->
    源3 RandomUser(真人脸) -> 源4 Pravatar(真人脸) -> 源5 GitHub(真人头像)。"""
    used = set(state.setdefault("used_avatar_urls", []))
    kw = (keywords or "").strip() or "portrait,face"
    kw_space = kw.replace(",", " ").strip()
    words = kw_space.split()
    kw_first = words[0] if words else "portrait"

    def try_pool(pool, src_name):
        random.shuffle(pool)
        for url, ext in pool[:5]:
            try:
                time.sleep(random.uniform(1.0, 3.0))  # 源级随机延迟，避免连发
                blob = http_download(url, timeout=15)

            except Exception:  # noqa: BLE001
                continue
            if _is_image_bytes(blob, ext):
                used.add(url)
                state["used_avatar_urls"] = sorted(used)
                ctype = "image/jpeg" if ext == "jpg" else f"image/{ext}"
                print(f"  [avatar] {nickname}: {src_name} 命中[{kw_space}]")
                return blob, f"{uuid.uuid4().hex}.{ext}", ctype
        return None

    # 源1：Wikimedia Commons（完整关键词 -> 首词 -> 通用词 三级降级）
    for q in (kw_space, kw_first, "portrait person"):
        pool = commons_search(q, used)
        if pool:
            got = try_pool(pool, "Commons")
            if got:
                return got

    # 源2：Openverse（按关键词搜 CC 图片）
    pool = fetch_openverse(kw_space)
    if pool:
        got = try_pool(pool, "Openverse")
        if got:
            return got

    # 源3：RandomUser 真人脸（每次随机不同人，用 used 防撞）
    for _ in range(3):
        ru = fetch_randomuser_avatar()
        if ru and ru[0] not in used and _is_image_bytes(ru[1], "jpg"):
            used.add(ru[0])
            state["used_avatar_urls"] = sorted(used)
            print(f"  [avatar] {nickname}: RandomUser 真人脸兜底")
            return ru[1], f"{uuid.uuid4().hex}.jpg", "image/jpeg"

    # 源4：Pravatar 真人脸（1~70 号随机，避开已用编号）
    nums = [n for n in range(1, 71)
            if f"i.pravatar.cc/400?img={n}" not in used]
    random.shuffle(nums)
    for n in nums[:5]:
        url = f"https://i.pravatar.cc/400?img={n}"
        try:
            time.sleep(random.uniform(1.0, 3.0))  # 源级随机延迟，避免连发
            blob = http_download(url, timeout=15)

        except Exception:  # noqa: BLE001
            continue
        if _is_image_bytes(blob, "jpg") or _is_image_bytes(blob, "png"):
            ext = "jpg" if _is_image_bytes(blob, "jpg") else "png"
            used.add(url)
            state["used_avatar_urls"] = sorted(used)
            ctype = "image/jpeg" if ext == "jpg" else "image/png"
            print(f"  [avatar] {nickname}: Pravatar 真人脸兜底(#{n})")
            return blob, f"{uuid.uuid4().hex}.{ext}", ctype

    # 源5：GitHub 真实用户/组织头像（极稳）
    users = GITHUB_AVATARS[:]
    random.shuffle(users)
    for u in users:
        url = f"https://github.com/{u}.png"
        if url in used:
            continue
        try:
            time.sleep(random.uniform(1.0, 3.0))  # 源级随机延迟，避免连发
            blob = http_download(url, timeout=15)

        except Exception:  # noqa: BLE001
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
        # 【新增】截断列表，防止内存和文件无限膨胀
        if "used_image_urls" in state:
            state["used_image_urls"] = state["used_image_urls"][-3000:]
        if "used_avatar_urls" in state:
            state["used_avatar_urls"] = state["used_avatar_urls"][-1000:]
        if "replied_comment_ids" in state:
            state["replied_comment_ids"] = state["replied_comment_ids"][-2000:]

        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 长期关系：按“我 -> 对方”保存，而不是把所有互动当作陌生人行为。
# affinity: 好感 [-1, 1]；familiarity: 熟悉度 [0, 1]
# ---------------------------------------------------------------------------
RELATION_MAX_PEERS = 120


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _relationship_bucket(affinity: float, familiarity: float) -> str:
    if familiarity >= 0.75 and affinity >= 0.35:
        return "熟悉的朋友"
    if familiarity >= 0.45 and affinity <= -0.25:
        return "熟悉但意见不太一致的人"
    if affinity >= 0.35:
        return "印象不错的关注对象"
    if affinity <= -0.35:
        return "观点常有分歧的对象"
    if familiarity >= 0.35:
        return "有过几次互动的熟人"
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
        "name": target_name or "对方",
        "affinity": 0.0,
        "familiarity": 0.0,
        "interactions": 0,
        "positive_interactions": 0,
        "disagreements": 0,
        "last_event": "尚未互动",
        "last_topic": "",
        "updated_at": 0,
    })
    if target_name:
        relation["name"] = target_name
    return relation


def relationship_context(state: dict, source: str, target: str, target_name: str) -> str:
    """提供给 LLM 的紧凑关系记忆，不泄露无关账号信息。"""
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    familiarity = float(relation.get("familiarity", 0))
    name = relation.get("name") or target_name or "对方"
    bucket = _relationship_bucket(affinity, familiarity)
    last_topic = relation.get("last_topic") or "没有特别记忆"
    return (
        f"关系记忆：这是「{name}」。你们过去互动过 {relation.get('interactions', 0)} 次；"
        f"你对 TA 的好感为 {affinity:.2f}，熟悉度为 {familiarity:.2f}，"
        f"目前是“{bucket}”。最近一次互动：{relation.get('last_event', '尚未互动')}；"
        f"关联话题：{last_topic}。请延续这段关系的语气，不要把 TA 当作陌生人。"
    )


def choose_interaction_stance(state: dict, source: str, target: str, target_name: str) -> str:
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    if affinity <= -0.25 and random.random() < 0.55:
        return "gentle_disagree"
    if affinity >= 0.25 and random.random() < 0.75:
        return "supportive"
    return "neutral"


def record_relationship(state: dict, source: str, target: str, target_name: str,
                        event: str, stance: str = "neutral", topic: str = "") -> None:
    """记录一次成功互动，并同步更新双方的长期印象。"""
    effects = {
        "like": (0.025, 0.035),
        "comment": (0.07, 0.12),
        "reply": (0.11, 0.16),
    }
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
        outgoing["last_event"] = {"like": "点赞了对方的动态", "comment": "评论了对方的动态", "reply": "回复了对方的评论"}.get(event, "产生了互动")
        outgoing["last_topic"] = topic[:80]
        outgoing["updated_at"] = int(time.time())

        # 对方也会因为被互动而形成印象，但强度更低，保留关系的方向性。
        reverse_name = _display_name_for(state, source, "对方")
        incoming = _ensure_relation(state, target, source, reverse_name)
        incoming_delta = affinity_delta * (0.7 if stance != "gentle_disagree" else 0.5)
        incoming["affinity"] = round(_clamp(float(incoming["affinity"]) + incoming_delta, -1, 1), 3)
        incoming["familiarity"] = round(_clamp(float(incoming["familiarity"]) + familiarity_delta * 0.75, 0, 1), 3)
        incoming["interactions"] = int(incoming["interactions"]) + 1
        incoming["positive_interactions"] = int(incoming["positive_interactions"]) + (stance != "gentle_disagree")
        incoming["disagreements"] = int(incoming["disagreements"]) + (stance == "gentle_disagree")
        incoming["last_event"] = {"like": "对方点赞了我的动态", "comment": "对方评论了我的动态", "reply": "对方回复了我的评论"}.get(event, "对方与我互动")
        incoming["last_topic"] = topic[:80]
        incoming["updated_at"] = int(time.time())

        # 每个账号只保留最近互动的有限关系，防止状态文件无限增长。
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
    """清理状态文件中已被后端明确删除的账号，避免历史缓存虚高。

    token 过期/网络失败时保留记录，交给 login_agent 后续重新登录，避免把仍存在的账号误删。
    """
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
        return {"phone": phone, "account": "DRY-" + uuid.uuid4().hex[:8],
                "token": "dry-token", "nickname": nickname}
    r = http_json("POST", "/user/login",
                  {"phone": phone, "code": code, "randomNum": code})
    data = (r or {}).get("data")
    data = data if isinstance(data, dict) else {}
    token = data.get("token")
    user = data.get("user") or {}
    if not token:
        print(f"  [login] 失败: {r}", file=sys.stderr)
        return None
    acc = {"phone": phone, "account": user.get("account"),
           "token": token, "nickname": nickname}
    state["accounts"][nickname] = acc
    save_state(state)
    return acc


def setup_profile(acc: dict, persona: dict, state: dict, dry_run: bool) -> bool:
    """昵称/签名 + 网络头像上传；任何一步失败 -> sys.exit 终止程序。"""
    if dry_run:
        print(f"[dry] {acc['nickname']}: GET getUser -> PUT /user -> POST /user/avatar")
        return True
    r = http_json("GET", "/user/getUser", params={"account": acc["account"]},
                  token=acc["token"])
    _u = (r or {}).get("data")
    user = _u if isinstance(_u, dict) else {}
    if not user.get("account"):
        sys.exit(f"[致命] {acc['nickname']} 获取用户信息失败，程序终止")

    # LLM/历史状态偶尔会返回空昵称；资料写入前必须保证 name 永远有值。
    nickname = str(persona.get("nickname") or acc.get("nickname") or "").strip()
    if not nickname:
        nickname = f"BoUser-{user['account'][:8]}"
        print(f"  [profile] {acc.get('nickname', user['account'])}: 昵称为空，使用兜底昵称 {nickname}", file=sys.stderr)

    def put_profile(av):
        payload = {"account": user["account"], "name": nickname,
                   "sign": persona["bio"], "phone": user.get("phone"), "avatar": av}
        return bool(http_json("PUT", "/user", payload, token=acc["token"],
                              raise_on_error=True))

    avatar_url = user.get("avatar")
    if not avatar_url:
        img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""), state)
        if not img:
            sys.exit(f"[致命] {acc['nickname']} 头像下载失败（所有源不可用），程序终止")
        data, fname, ctype = img
        up = http_multipart("POST", "/user/avatar",
                            fields={"account": acc["account"]}, file_field="avatar",
                            filename=fname, file_bytes=data, content_type=ctype,
                            token=acc["token"])
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

    check = http_json("GET", "/user/getUser", params={"account": acc["account"]},
                      token=acc["token"])
    _g = (check or {}).get("data")
    got = _g if isinstance(_g, dict) else {}
    if got.get("name") != nickname:
        sys.exit(f"[致命] {acc['nickname']} 回读校验失败 name={got.get('name')!r}")
    print(f"[profile] {acc['nickname']}: OK name='{got.get('name')}' "
          f"avatar={got.get('avatar') or '无'}")
    return True


# ---------------------------------------------------------------------------
# 社交动作
# ---------------------------------------------------------------------------
def fetch_post_comments(post_id: str, acc: dict) -> list:
    """获取某条帖子下的所有评论"""
    r = http_json("GET", "/comments/getComments",
                  params={"postId": post_id, "page": 1, "size": 20},
                  token=acc["token"])
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


def check_and_reply_interactions(acc: dict, state: dict, dry_run: bool):
    """回访我的帖子，检查新评论并根据性格回复"""
    nick = acc["nickname"]
    print(f"🔔 [{nick}] 正在检查是否有新互动...")

    # 1. 获取我最近发布的 5 条帖子
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    my_posts = (r or {}).get("data") or []
    if not my_posts:
        return

    replied_ids = set(state.setdefault("replied_comment_ids", []))
    new_replies = []

    for post in my_posts[:5]:
        pid = post.get("id")
        if not pid: continue

        comments = fetch_post_comments(pid, acc)
        for cmt in comments:
            cmt_id = cmt.get("id")
            cmt_account = cmt.get("account")
            cmt_text = cmt.get("comments") or cmt.get("text", "")

            # 过滤：不是自己的评论，且未回复过，且不是回复别人的子评论(简化逻辑：只回复一级评论)
            if cmt_account and cmt_account != acc["account"] and cmt_id not in replied_ids and not cmt.get("parentId"):
                new_replies.append({"post_id": pid, "comment_id": cmt_id, "text": cmt_text, "author": cmt_account})

    if not new_replies:
        print(f"🔕 [{nick}] 没有新的未回复互动。")
        return

    # 2. 根据性格决定是否回复 (高冷性格回复概率低，热情性格回复概率高)
    personality = acc.get("personality", "普通")
    reply_chance = 0.9 if "热情" in personality or "话痨" in personality else \
        0.3 if "高冷" in personality or "社恐" in personality else 0.6

    for item in new_replies:
        time.sleep(random.uniform(1.0, 3.0))  # 模拟思考时间
        if random.random() > reply_chance:
            print(f"🙅 [{nick}] 性格使然，决定忽略评论: '{item['text'][:20]}...'")
            continue

        print(f"💬 [{nick}] 发现新评论，准备以【{personality} 性格回复: '{item['text'][:20]}...'")

        if dry_run:
            print(f"[dry] [{nick}] 回复评论 {item['comment_id'][:8]}")
            continue

        # 生成回复内容
        commenter_name = _display_name_for(state, item["author"], "这位评论者")
        stance = choose_interaction_stance(state, acc["account"], item["author"], commenter_name)
        reply_text = gen_text("comment", {
            **acc,
            "target": item["text"],
            "interaction_stance": stance,
            "relationship_context": relationship_context(
                state, acc["account"], item["author"], commenter_name),
        })

        # 发送回复 (parentId 设为原评论 ID)
        r = http_json("POST", "/comments/post",
                      {"postsId": item["post_id"], "account": acc["account"],
                       "comments": reply_text, "parentId": item["comment_id"],
                       "replyToAccount": item["author"]},
                      token=acc["token"])
        if r and r.get("code") == 1:
            print(f"✅ [{nick}] 回复成功: '{reply_text[:30]}...'")
            with state_lock:
                state.setdefault("replied_comment_ids", []).append(item["comment_id"])
            record_relationship(state, acc["account"], item["author"], commenter_name,
                                "reply", stance, item["text"])
            save_state(state)
        else:
            print(f"❌ [{nick}] 回复失败")
def create_post(acc: dict, text: str, dry_run: bool):
    if dry_run:
        print(f"[dry] {acc['nickname']} 发帖: {text[:50]}")
        return "dry-post-id"
    r = http_json("POST", "/posts/post",
                  {"account": acc["account"], "text": text}, token=acc["token"])
    if r and r.get("code") == 1:
        pid = r.get("data")
        print(f"[post] {acc['nickname']}: OK id={pid} - {text[:30]}")
        return pid
    print(f"[post] {acc['nickname']}: FAIL - {text[:30]}")
    return None


def create_post_with_images(acc: dict, text: str, images: list, dry_run: bool):
    pid = create_post(acc, text, dry_run)
    if not pid:
        return None
    for data, fname, ctype, _t in images:
        up = http_multipart("POST", "/image/post",
                            fields={"account": acc["account"], "postId": pid},
                            file_field="images", filename=fname, file_bytes=data,
                            content_type=ctype, token=acc["token"])
        if not (up and up.get("code") == 1):
            print(f"[post] 图片上传失败，回滚删帖 {pid[:8]}", file=sys.stderr)
            http_json("DELETE", f"/posts/delete/{pid}",
                      params={"account": acc["account"]}, token=acc["token"])
            return None
    if images:
        print(f"[post] {acc['nickname']}: {len(images)} 张图片绑定成功")
    return pid


def comment_post(acc: dict, post_id: str, text: str, target_account: str, dry_run: bool):
    if dry_run:
        print(f"[dry] {acc['nickname']} 评论 {post_id[:8]}: {text[:40]}")
        return True
    r = http_json("POST", "/comments/post",
                  {"postsId": post_id, "account": acc["account"], "comments": text,
                   "parentId": "", "replyToAccount": target_account or ""},
                  token=acc["token"])
    ok = bool(r) and r.get("code") == 1
    print(f"[comment] {acc['nickname']}: {'OK' if ok else 'FAIL'} - {text[:20]}")
    return ok


def like_post(acc: dict, post_id: str, dry_run: bool):
    if dry_run:
        print(f"[dry] {acc['nickname']} 点赞 {post_id[:8]}")
        return True
    r = http_json("POST", "/like",
                  {"account": acc["account"], "postId": post_id}, token=acc["token"])
    ok = bool(r) and r.get("code") == 1
    print(f"[like] {acc['nickname']}: {'OK' if ok else 'FAIL'} {post_id[:8]}")
    return ok


# ---------------------------------------------------------------------------
# 发帖（0~9 图）与用户会话（流水席核心）
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
            print(f"[post] {acc['nickname']}: 图片下载失败/库存不足，放弃本条发帖",
                  file=sys.stderr)
            save_state(state)
            return None
        _topic, desc, imgs = got
        content = gen_post_from_images(acc, desc, imgs)
        print(f"[post-plan] {acc['nickname']}: {n_img} 张图 主题='{desc}'")
    pid = create_post_with_images(acc, content, imgs, False)
    save_state(state)
    return pid


def simulate_user_session(acc: dict, state: dict, dry_run: bool):
    """一个人上线 -> 填资料 -> 偏好浏览(同语言加权) -> 随机互动/发帖 -> 回访旧帖 -> 下线"""
    nick = acc["nickname"]
    lang_code = acc.get("lang_code", "unknown")
    print(f"📱 [{nick}] ({acc.get('nationality')}) 上线了，开始刷动态…")

    if dry_run:
        print(f"[dry] [{nick}] 浏览(偏好{acc.get('language')}) -> 随机互动 -> 发帖 -> 回访 -> 下线")
        return

    # 1. 懒加载：首次上线完善资料
    if not state["accounts"].get(nick, {}).get("profile_done"):
        time.sleep(random.uniform(3.0, 15.0))
        throttle_avatar()
        persona = {"nickname": nick, "bio": acc.get("bio", ""), "avatar_desc": acc.get("avatar_desc", "")}
        setup_profile(acc, persona, state, False)
        state["accounts"][nick]["profile_done"] = True
        state["accounts"][nick]["bio"] = acc.get("bio", "")
        state["accounts"][nick]["avatar_desc"] = acc.get("avatar_desc", "")
        state["accounts"][nick]["personality"] = acc.get("personality", "普通")
        save_state(state)

    # 2. 获取广场帖子
    posts = fetch_latest_posts(acc, limit=40)  # 扩大获取基数以便加权采样
    if not posts:
        print(f"📱 [{nick}] 广场没帖子，溜了溜了")
        return

    # 3. 【核心新增】语言偏好加权浏览
    weights = []
    for post in posts:
        ptext = post.get("text", "")
        p_lang = detect_lang(ptext)
        # 同语言权重为 5，异语言权重为 1 (即同语言被抽中的概率是异语言的 5 倍)
        weight = 5 if p_lang == lang_code or lang_code == "unknown" else 1
        # 有长期互动的人更容易被再次看到；负向关系也保留适度重逢，形成持续但克制的观点分歧。
        relation = state.get("relationships", {}).get(acc["account"], {}).get(post.get("account", ""))
        if relation:
            familiarity = float(relation.get("familiarity", 0))
            affinity = abs(float(relation.get("affinity", 0)))
            weight *= 1 + min(2.5, familiarity * 2.2 + affinity * 0.8)
        weights.append(weight)

    # 使用加权随机采样浏览 3~8 条帖子
    browse_count = min(random.randint(3, 8), len(posts))
    try:
        browse = random.choices(posts, weights=weights, k=browse_count)
    except ValueError:
        browse = random.sample(posts, browse_count)  # 兜底

    # 4. 浏览与互动
    for post in browse:
        time.sleep(random.uniform(2.0, 5.0))
        pid = post.get("id")
        ptext = post.get("text", "")
        pauthor = post.get("account", "")
        if not pid or pauthor == acc["account"]:
            continue

        author_data = post.get("user") if isinstance(post.get("user"), dict) else {}
        author_name = author_data.get("name") or _display_name_for(state, pauthor, "这位作者")

        if post.get("isLike") == 0 and random.random() < SESSION_CFG["like"]:
            if like_post(acc, pid, False):
                record_relationship(state, acc["account"], pauthor, author_name,
                                    "like", "supportive", ptext)
            time.sleep(random.uniform(0.5, 1.5))

        if random.random() < SESSION_CFG["comment"]:
            print(f"💬 [{nick}] 看了 '{ptext[:15]}…' 想评论一下")
            stance = choose_interaction_stance(state, acc["account"], pauthor, author_name)
            c = gen_text("comment", {
                **acc,
                "target": ptext,
                "interaction_stance": stance,
                "relationship_context": relationship_context(
                    state, acc["account"], pauthor, author_name),
            })
            if comment_post(acc, pid, c, pauthor, False):
                record_relationship(state, acc["account"], pauthor, author_name,
                                    "comment", stance, ptext)
            time.sleep(random.uniform(2.0, 4.0))

    # 5. 随机发帖
    if random.random() < SESSION_CFG["post"]:
        print(f"✍️ [{nick}] 突然有了分享欲，准备发帖…")
        publish_a_post(acc, state)
        time.sleep(random.uniform(2.0, 5.0))
        # 发帖后，顺便检查一下之前的帖子有没有人互动
        check_and_reply_interactions(acc, state, False)
    else:
        # 即使不发帖，也有一定概率回访旧帖
        if random.random() < 0.4:
            check_and_reply_interactions(acc, state, False)

    save_state(state)

    print(f"👋 [{nick}] 刷累了，下线休息。")


# ---------------------------------------------------------------------------
# 主流程：阶段一串行备号 -> 阶段二线程池流水席
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="AI 社区模拟机器人（流水席版）")
    ap.add_argument("--agents", type=int, default=500, help="账号池总数")
    ap.add_argument("--concurrent", type=int, default=50, help="同时在线人数")
    ap.add_argument("--like-chance", type=float, default=0.40)
    ap.add_argument("--comment-chance", type=float, default=0.15)
    ap.add_argument("--post-chance", type=float, default=0.10)
    ap.add_argument("--no-avatar", action="store_true", help="跳过资料/头像设置")
    ap.add_argument("--interval", type=float, default=0.5, help="备号阶段请求间隔")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    args = ap.parse_args()

    SESSION_CFG.update({"like": args.like_chance,
                        "comment": args.comment_chance,
                        "post": args.post_chance})

    if not LLM_KEY:
        sys.exit("[致命] 必须设置 BOT_LLM_KEY。例: export BOT_LLM_KEY=sk-xxx")
    print(f"[llm] 使用模型 {LLM_MODEL} @ {LLM_URL}")

    state = load_state()

    # ---------- 阶段一：串行准备账号池 ----------
    # ---------- 阶段一：账号池复用 + 差额补注册 ----------
    print(f"=== 阶段一：准备 {args.agents} 个账号（优先复用历史账号池） ===")
    pool = state.setdefault("accounts", {})
    prune_deleted_accounts(state)
    existing = [n for n in pool.keys() if pool[n].get("account")]
    reuse = random.sample(existing, min(args.agents, len(existing))) if existing else []
    need_new = max(0, args.agents - len(reuse))
    print(f"[pool] 后端有效历史账号池 {len(existing)} 个 | 本次复用 {len(reuse)} 个 | 需新注册 {need_new} 个")

    prepared, seen = [], set(reuse)
    # 1) 复用老账号（token 失效会自动重登，头像/资料已_done 不会重复下载）
    for nick in reuse:
        cached = pool[nick]
        acc = login_agent(state, nick, args.dry_run)
        if not acc:
            continue
        acc["bio"] = cached.get("bio") or state.get("personas", {}).get(nick, "")
        acc["avatar_desc"] = cached.get("avatar_desc", "")
        prepared.append(acc)
        time.sleep(args.interval)
    # 2) 差额新注册：只拿 token，头像/资料懒加载到阶段二第一次上线（分散请求）
    for i in range(need_new):
        used_pool = list(seen) + [p["nickname"] for p in prepared] + list(pool.keys())
        persona = gen_persona(i + 1, used_pool)
        if persona["nickname"] in seen:
            continue
        seen.add(persona["nickname"])
        state.setdefault("personas", {})[persona["nickname"]] = persona["bio"]
        print(f"[persona] 新注册 {persona['nickname']}：{persona['bio']}")
        acc = login_agent(state, persona["nickname"], args.dry_run)
        if not acc:
            continue
        acc["bio"] = persona["bio"]
        acc["avatar_desc"] = persona.get("avatar_desc", "")
        prepared.append(acc)
        time.sleep(args.interval)
    save_state(state)
    print(f"=== 账号就绪：{len(prepared)} 个（老号 {len(reuse)} + 新号 {len(prepared) - len(reuse)}） ===")

    # ---------- 阶段二：流水席模拟 ----------
    print(f"\n=== 阶段二：流水席模拟（同时在线 {args.concurrent} 人） ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrent) as ex:
        futures = [ex.submit(simulate_user_session, acc, state, args.dry_run)
                   for acc in prepared]
        concurrent.futures.wait(futures)

    save_state(state)
    print(f"\n🎉 完成：{len(prepared)} 个账号轮流刷完社区。"
          f"状态缓存: {STATE_FILE}")


if __name__ == "__main__":
    main()
