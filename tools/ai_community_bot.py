#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 社区模拟机器人（多模型负载均衡 & 自然增长 & 流式启动 & 终极整合版 V3.2-RealImages）
优化：严格 Provider 容量控制、Future 异常收集与熔断、动态贪心调度防饥饿、
      RLock 防死锁、防抖异步写盘解决高并发 I/O 瓶颈、静默 404 防刷屏、
      全面恢复从真实社交平台/图库 (Reddit/Openverse/Picsum) 抓取图片、支持 WebP。
"""
from __future__ import annotations

import argparse
import base64
import traceback
import concurrent.futures
import copy
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
import functools

import logging
import logging.handlers
from datetime import datetime

# 🛡️ Windows 控制台 UTF-8 兼容性修复
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# ---------------------------------------------------------------------------
# 📝 完整行为日志系统配置
# ---------------------------------------------------------------------------
LOG_DIR = os.environ.get("BOT_LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "agent": getattr(record, "agent", "SYSTEM"),
            "action": getattr(record, "action", "UNKNOWN"),
            "target": getattr(record, "target", ""),
            "details": getattr(record, "details", ""),
            "mental_state": getattr(record, "mental_state", "normal"),
            "message": record.getMessage()
        }
        return json.dumps({k: v for k, v in log_record.items() if v != "" and v is not None}, ensure_ascii=False)


behavior_logger = logging.getLogger("AgentBehavior")
behavior_logger.setLevel(logging.INFO)
behavior_logger.propagate = False

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(agent)s: %(message)s"))
behavior_logger.addHandler(console_handler)

file_handler = logging.handlers.RotatingFileHandler(
    filename=os.path.join(LOG_DIR, "agent_actions.log"),
    maxBytes=50 * 1024 * 1024, backupCount=10, encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(JsonFormatter())
behavior_logger.addHandler(file_handler)


def log_action(agent: dict, action: str, target: str = "", details: str = "", level: str = "INFO"):
    extra = {
        "agent": agent.get("nickname", "Unknown"), "action": action, "target": str(target),
        "details": str(details)[:500], "mental_state": agent.get("current_mental_state", "normal")
    }
    msg = f"Action: {action}"
    if details:
        msg += f" | Details: {details}"

    if level == "INFO":
        behavior_logger.info(msg, extra=extra)
    elif level == "WARNING":
        behavior_logger.warning(msg, extra=extra)
    elif level == "ERROR":
        behavior_logger.error(msg, extra=extra)


print = functools.partial(print, flush=True)

# ---------------------------------------------------------------------------
# 🛡️ 全局配置与锁 (升级 RLock 与 防抖写盘)
# ---------------------------------------------------------------------------
factory_stop_event = threading.Event()
_ready_accounts_changed = threading.Event()
_ready_accounts_lock = threading.Lock()
_ready_account_names = set()
_used_images_lock = threading.Lock()
_used_images_set = set()
_active_sessions_lock = threading.Lock()
_active_sessions_count = 0
_total_accounts_count = 0


def mark_account_ready(nickname: str) -> None:
    with _ready_accounts_lock:
        _ready_account_names.add(nickname)
    _ready_accounts_changed.set()


def is_account_ready(nickname: str) -> bool:
    with _ready_accounts_lock:
        return nickname in _ready_account_names


def ready_account_count() -> int:
    with _ready_accounts_lock:
        return len(_ready_account_names)

_api_cache_lock = threading.Lock()
_api_cache = {}
_image_download_lock = threading.Lock()
_last_image_download_ts = [0.0]
IMAGE_DOWNLOAD_MIN_GAP = float(os.environ.get("BOT_IMG_GAP", "0.5"))
DWELL_TIME_SCALE = max(0.01, float(os.environ.get("BOT_DWELL_TIME_SCALE", "1.0")))
ENABLE_EXTERNAL_POST_IMAGES = os.environ.get("BOT_ENABLE_EXTERNAL_POST_IMAGES", "true").lower() in {
    "1", "true", "yes", "on"
}


def throttle_image_download():
    with _image_download_lock:
        now = time.time()
        wait = IMAGE_DOWNLOAD_MIN_GAP - (now - _last_image_download_ts[0])
        if wait > 0: time.sleep(wait)
        _last_image_download_ts[0] = time.time()


BASE = os.environ.get("BOWALL_BASE", "http://localhost:8080")
UA = {"User-Agent": "Mozilla/5.0 (compatible; AiCommunityBot/1.0)"}

state_lock = threading.RLock()
avatar_lock = threading.Lock()
_last_avatar_ts = [0.0]
AVATAR_MIN_GAP = float(os.environ.get("BOT_AVATAR_GAP", "8"))


def throttle_avatar():
    with avatar_lock:
        now = time.time()
        wait = AVATAR_MIN_GAP - (now - _last_avatar_ts[0])
        if wait > 0: time.sleep(wait)
        _last_avatar_ts[0] = time.time()


_state_revision = 0
_saved_state_revision = 0
_last_save_time = 0.0
_state_dirty_lock = threading.Lock()
_state_file_lock = threading.Lock()
SAVE_INTERVAL = 30.0


def mark_state_dirty():
    global _state_revision
    with _state_dirty_lock:
        _state_revision += 1


def flush_state(state: dict, force: bool = False):
    global _saved_state_revision, _last_save_time
    now = time.time()
    with _state_dirty_lock:
        target_revision = _state_revision
        should_save = force or (target_revision > _saved_state_revision and now - _last_save_time >= SAVE_INTERVAL)
    if not should_save: return
    save_state(state)
    with _state_dirty_lock:
        _saved_state_revision = max(_saved_state_revision, target_revision)
        _last_save_time = now


SESSION_CFG = {"like": 0.40, "comment": 0.15, "post": 0.10}

# ---------------------------------------------------------------------------
# 🌟 多模型提供商池 & 全局字典
# ---------------------------------------------------------------------------
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
    "高冷": -0.08, "社恐": -0.05, "随性": 0.02, "幽默": 0.06
}

_DEFAULT_PROVIDERS = [
    {
        "name": "deepseek", "url": os.environ.get("BOT_DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"),
        "key": os.environ.get("BOT_DEEPSEEK_KEY", os.environ.get("BOT_LLM_KEY", "")),
        "model": os.environ.get("BOT_DEEPSEEK_MODEL", "deepseek-chat"),
        "vlm_url": os.environ.get("BOT_VLM_URL", ""), "vlm_key": os.environ.get("BOT_VLM_KEY", ""),
        "vlm_model": os.environ.get("BOT_VLM_MODEL", ""),
        "capacity": 30, "semaphore": threading.Semaphore(3)
    },
    {
        "name": "qwen",
        "url": os.environ.get("BOT_QWEN_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        "key": os.environ.get("BOT_QWEN_KEY", ""), "model": os.environ.get("BOT_QWEN_MODEL", "qwen-plus"),
        "vlm_url": os.environ.get("BOT_QWEN_VLM_URL",
                                  "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        "vlm_key": os.environ.get("BOT_QWEN_VLM_KEY", os.environ.get("BOT_QWEN_KEY", "")),
        "vlm_model": os.environ.get("BOT_QWEN_VLM_MODEL", "qwen-vl-max"),
        "capacity": 30, "semaphore": threading.Semaphore(3)
    }
]

_env_providers = os.environ.get("BOT_LLM_PROVIDERS")
if _env_providers:
    try:
        LLM_PROVIDERS = json.loads(_env_providers)
        for p in LLM_PROVIDERS:
            p.setdefault("semaphore", threading.Semaphore(3))
            p.setdefault("capacity", 30)
    except Exception:
        LLM_PROVIDERS = _DEFAULT_PROVIDERS
else:
    LLM_PROVIDERS = _DEFAULT_PROVIDERS


def get_available_providers() -> list:
    return [p for p in LLM_PROVIDERS if all(p.get(field) for field in ("name", "url", "key", "model"))]


def get_provider_config(provider_name: str | None) -> dict:
    available = get_available_providers()
    for p in available:
        if p["name"] == provider_name: return p
    if available: return available[0]
    raise RuntimeError("没有配置完整且可用的 LLM provider")


def get_default_provider_name() -> str: return get_provider_config(None)["name"]


_provider_assign_lock = threading.Lock()


def assign_llm_provider(state: dict, allow_overflow: bool = False) -> dict | None:
    with _provider_assign_lock:
        available = get_available_providers()
        if not available: raise RuntimeError("无法分配账号：没有配置完整且可用的 LLM provider")
        counts = {p["name"]: 0 for p in available}
        for acc in state.get("accounts", {}).values():
            prov = acc.get("llm_provider")
            if prov in counts: counts[prov] += 1
        for p in available:
            if counts[p["name"]] < p["capacity"]: return p
        if allow_overflow:
            return min(available, key=lambda p: counts[p["name"]] / max(1, int(p["capacity"])))
        return None


IMAGE_TOPICS = [
    ("Coffee", "咖啡馆/手冲咖啡的暖色调照片"), ("Cats", "家猫日常照片"), ("Sunset", "日落晚霞风景照"),
    ("Street food", "街头小吃/夜市食物照片"), ("City skyline at night", "城市夜景天际线"),
    ("Houseplant", "室内绿植/阳台盆栽"), ("Bicycle", "骑行/街边自行车"), ("Beach", "海边沙滩风景"),
    ("Mountain hiking", "登山徒步山景"), ("Books", "书桌/书架/阅读角落"),
]
ALLOWED_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
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


def detect_lang(text: str) -> str:
    if not text: return "unknown"
    if re.search(r'[\u4e00-\u9fff]', text): return "zh"
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text): return "ja"
    if re.search(r'[\uAC00-\uD7AF]', text): return "ko"
    if re.search(r'[\u0400-\u04FF]', text): return "ru"
    if re.search(r'[àâäéèêëïîôùûüÿçœæñ]', text, re.I): return "es"
    return "en"


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")
CREDENTIALS_FILE = os.environ.get("BOT_CREDENTIALS_FILE",
                                  os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_credentials.json"))
SENSITIVE_ACCOUNT_FIELDS = ("phone", "token", "token_issued_at")


# ---------------------------------------------------------------------------
# 基础网络层
# ---------------------------------------------------------------------------
def http_download(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp: return resp.read()


def http_multipart(method: str, path: str, fields: dict, file_field: str, filename: str, file_bytes: bytes,
                   content_type: str, token=None):
    url = BASE + path
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items(): parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
    parts.append((
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n").encode(
        "utf-8"))
    parts.append(file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token: headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [upload] {method} {path} -> {e}", file=sys.stderr)
    return None


class ApiError(Exception): pass


def http_json(method: str, path: str, body=None, token=None, params=None, raise_on_error=False, silent_404=False):
    url = BASE + path
    if params: url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404 and silent_404:
            return None
        print(f"  [http] {method} {path} -> {e.code}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [http] {method} {path} -> {e}", file=sys.stderr)
        return None
    if isinstance(r, dict) and r.get("code") not in (1, None):
        msg = r.get("msg")
        if raise_on_error: raise ApiError(f"{method} {path}: {msg}")
    return r


# ---------------------------------------------------------------------------
# LLM 接入层
# ---------------------------------------------------------------------------
def llm_generate(prompt: str, provider_name: str, max_retry: int = 5, max_tokens: int = 200) -> str | None:
    prov = get_provider_config(provider_name)
    if not prov.get("key"): return None
    payload = json.dumps({"model": prov["model"], "messages": [{"role": "user", "content": prompt}], "temperature": 1.1,
                          "max_tokens": max_tokens}).encode("utf-8")
    for i in range(max_retry):
        try:
            with prov["semaphore"]:
                req = urllib.request.Request(prov["url"], data=payload, headers={"Content-Type": "application/json",
                                                                                 "Authorization": f"Bearer {prov['key']}"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    return d["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (i + 1))
            else:
                time.sleep(2 + i)
        except Exception:
            time.sleep(2 + i)
    return None


def llm_vision_generate(items: list, prompt: str, provider_name: str, max_tokens: int = 200):
    prov = get_provider_config(provider_name)
    vlm_url = prov.get("vlm_url") or prov.get("url")
    vlm_key = prov.get("vlm_key") or prov.get("key")
    vlm_model = prov.get("vlm_model") or prov.get("model")
    if not (vlm_url and vlm_key): return None
    content = [{"type": "text", "text": prompt}]
    for b64, ctype in items: content.append({"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}})
    payload = json.dumps({"model": vlm_model, "messages": [{"role": "user", "content": content}], "temperature": 1.0,
                          "max_tokens": max_tokens}).encode("utf-8")
    try:
        with prov["semaphore"]:
            req = urllib.request.Request(vlm_url, data=payload, headers={"Content-Type": "application/json",
                                                                         "Authorization": f"Bearer {vlm_key}"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [vlm-{prov['name']}] 视觉模型调用失败: {e}", file=sys.stderr)
        return None


def _clean_llm_text(s: str) -> str:
    s = s.strip()
    if s.startswith("```"): s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    return s.strip().strip("`").strip("\"'“”").strip()


# ---------------------------------------------------------------------------
# 🌟 图片抓取 (全面恢复真实社交平台/图库链路)
# ---------------------------------------------------------------------------
def _is_image_bytes(data: bytes, ext: str) -> bool:
    if ext == "jpg": return data[:3] == b"\xff\xd8\xff"
    if ext == "png": return data[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == "gif": return data[:6] in (b"GIF87a", b"GIF89a")
    if ext == "webp": return data[:4] == b"RIFF" and len(data) > 11 and data[8:12] == b"WEBP"
    # 兜底：直接检查文件头
    if data[:3] == b"\xff\xd8\xff": return True
    if data[:8] == b"\x89PNG\r\n\x1a\n": return True
    if data[:4] == b"RIFF" and len(data) > 11 and data[8:12] == b"WEBP": return True
    return False


def fetch_reddit_images(query: str, n: int) -> list:
    """🌟 从主流社交平台 Reddit 抓取真实 UGC 图片 (优化 UA 与超时)"""
    subreddit_map = {
        "travel": "travel", "trip": "travel", "mountain": "EarthPorn", "beach": "beach",
        "food": "food", "coffee": "Coffee", "cafe": "Coffee", "recipe": "food",
        "cat": "cats", "dog": "dogs", "pet": "aww",
        "city": "CityPorn", "skyline": "CityPorn", "street": "streetphotography",
        "tech": "technology", "code": "ProgrammerHumor",
        "book": "books", "reading": "books",
        "fitness": "fitness", "yoga": "yoga", "run": "running",
        "sunset": "sunset", "nature": "natureporn",
        "music": "music", "art": "Art", "photo": "photography",
        "bicycle": "bicycling", "plant": "houseplants"
    }

    sub = "pics"
    query_lower = query.lower()
    for k, v in subreddit_map.items():
        if k in query_lower:
            sub = v
            break

    # 🛡️ 使用标准现代浏览器 UA，大幅降低 403 概率
    reddit_ua = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit=30"

    try:
        req = urllib.request.Request(url, headers=reddit_ua)
        # 🛡️ 缩短超时时间至 6 秒，避免阻塞主流程
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        images = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            img_url = post.get("url", "")
            title = post.get("title", "")

            if img_url.endswith((".jpg", ".jpeg", ".png", ".webp")) and "i.redd.it" in img_url:
                mime = "image/webp" if img_url.endswith(".webp") else "image/jpeg"
                images.append((img_url, mime, title))
                if len(images) >= n * 2: break

        random.shuffle(images)
        if images:
            print(f"  [Reddit] 从 r/{sub} 成功获取 {len(images)} 张真实社交图片")
        return images
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"  [Reddit] 访问被拒 (403)，已自动无缝切换至备用真实图库")
        else:
            print(f"  [Reddit] 接口异常 (HTTP {e.code})")
        return []
    except Exception:
        return []

    sub = "pics"
    query_lower = query.lower()
    for k, v in subreddit_map.items():
        if k in query_lower:
            sub = v
            break

    reddit_ua = {"User-Agent": "AiCommunityBot/1.0 (Educational Simulation Script)"}
    url = f"https://www.reddit.com/r/{sub}/hot.json?limit=50"

    try:
        req = urllib.request.Request(url, headers=reddit_ua)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        images = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            img_url = post.get("url", "")
            title = post.get("title", "")

            if img_url.endswith((".jpg", ".jpeg", ".png", ".webp")) and "i.redd.it" in img_url:
                mime = "image/webp" if img_url.endswith(".webp") else "image/jpeg"
                images.append((img_url, mime, title))
                if len(images) >= n * 3: break

        random.shuffle(images)
        print(f"  [Reddit] 从 r/{sub} 成功获取 {len(images)} 张真实社交图片")
        return images
    except urllib.error.HTTPError as e:
        print(f"  [Reddit] 接口限流或拒绝访问 (HTTP {e.code})")
        return []
    except Exception as e:
        print(f"  [Reddit] 抓取异常: {e}")
        return []


def fetch_openverse_pool(query: str) -> list:
    page = random.randint(1, 15)
    api = f"https://api.openverse.org/v1/images/?page_size=40&page={page}&q={urllib.parse.quote(query)}&format=json"
    try:
        req = urllib.request.Request(api, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip().startswith("{"): return []
            data = json.loads(raw)
        out = []
        for item in data.get("results", []):
            url = item.get("url") or item.get("thumbnail")
            if url: out.append((url, "image/jpeg", item.get("title", "")))
        return out
    except Exception:
        return []


def fetch_openverse_pool_cached(query: str) -> list:
    with _api_cache_lock:
        if query in _api_cache: return _api_cache[query]
        if len(_api_cache) > 500:
            keys_to_del = list(_api_cache.keys())[:250]
            for k in keys_to_del: _api_cache.pop(k, None)
    pool = fetch_openverse_pool(query)
    with _api_cache_lock:
        _api_cache[query] = pool
    return pool


def fetch_loremflickr(tags: str, n: int) -> list:
    images = []
    clean_tags = ",".join([t.strip() for t in tags.split(",") if t.strip()]) or "daily,life"
    for _ in range(n):
        lock = random.randint(1, 999999)
        url = f"https://loremflickr.com/800/600/{urllib.parse.quote(clean_tags, safe=',')}?lock={lock}"
        images.append((url, "image/jpeg", tags))
    return images


def fetch_picsum(n: int) -> list:
    """🌟 终极真实摄影图片兜底服务"""
    images = []
    for _ in range(n):
        url = f"https://picsum.photos/800/600?random={random.randint(1, 999999)}"
        images.append((url, "image/jpeg", "random daily life"))
    return images


def pick_and_download_images(n: int, search_tags: str) -> tuple:
    global _used_images_set

    pool = []

    # 🌟 优先级 1：开放版权高质量图库 (Openverse) - 稳定且高质量
    pool.extend(fetch_openverse_pool_cached(search_tags))

    # 🌟 优先级 2：真实摄影兜底 (Picsum) - 100% 稳定，全是真实摄影师作品
    if len(pool) < n:
        pool.extend(fetch_picsum(n * 2))

    # 🌟 优先级 3：标签随机图床 (LoremFlickr)
    if len(pool) < n:
        pool.extend(fetch_loremflickr(search_tags, n * 2))

    # 🌟 优先级 4：主流社交平台 (Reddit) - 作为丰富度补充，若 403 则快速跳过
    if len(pool) < n * 2:
        pool.extend(fetch_reddit_images(search_tags, n))

    random.shuffle(pool)
    images = []

    print(f"  [📸 抓图] 目标 {n} 张，混合候选池大小: {len(pool)}")

    for url, mime, title in pool:
        with _used_images_lock:
            if url in _used_images_set: continue
            _used_images_set.add(url)

        throttle_image_download()
        try:
            # 🛡️ 单图下载超时设为 10 秒，防止个别死链卡死线程
            data = http_download(url, timeout=10)
        except Exception:
            continue

        ext = "jpg"
        if not _is_image_bytes(data, "jpg"):
            if _is_image_bytes(data, "png"):
                ext = "png"
            elif _is_image_bytes(data, "webp"):
                ext = "webp"
            else:
                continue

        ctype = f"image/{ext}"
        images.append((data, f"{uuid.uuid4().hex}.{ext}", ctype, title))
        if len(images) == n: break

    if len(images) == n:
        print(f"  [📸 抓图] 成功获取 {n} 张真实图片")
        return search_tags, search_tags, images

    print(f"  [📸 抓图] 失败，仅获取到 {len(images)}/{n} 张图片")
    return None


def gen_post_from_images(persona: dict, desc: str, images: list, max_tokens: int = 200,
                         mental_state: str = "normal") -> str | None:
    titles = "、".join(t for *_, t in images if t)
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"
    mental_prompts = {
        "inferior": "（心理状态：自卑）你说话小心翼翼，缺乏自信，经常使用'可能'、'也许'、'我不懂但'，倾向于讨好，不敢表达强烈观点。",
        "arrogant": "（心理状态：自大/优越感）你充满优越感，喜欢凡尔赛、说教、指点江山。经常使用'其实'、'说白了'、'你们可能不知道'，喜欢贬低他人以抬高自己。",
        "depressed": "（心理状态：压抑/Emo）你感到疲惫、无力。文字充满丧文化、深夜emo感，喜欢用省略号，表达对生活的无奈和虚无感，配图只是你发呆的窗口。"
    }
    mental_instruction = mental_prompts.get(mental_state, "")
    vlm_images = images[:3]
    provider_name = persona.get("llm_provider") or get_default_provider_name()

    out = llm_vision_generate(
        [(base64.b64encode(d).decode(), ct) for d, _, ct, _ in vlm_images],
        f"这是我即将发布的 {len(images)} 张照片。{lang_req} {mental_instruction} 请以一个年轻网友的口吻写一条 30~150 字帖子正文，只输出正文。",
        provider_name, max_tokens=max_tokens)

    if not out:
        out = llm_generate(
            f"你是社区用户「{persona['nickname']}」（{persona['nationality']}人，性格：{persona['personality']}，职业：{persona.get('occupation', '未知')}）。{lang_req} {mental_instruction} 你刚拍了 {len(images)} 张照片准备发帖，主题：{desc}。请写一条 30~150 字帖子正文。\n注意：直接输出正文内容，绝对不要包含任何 JSON 格式、不要加引号、不要加标题、不要说'好的'。",
            provider_name, max_tokens=max_tokens)

    out = _clean_llm_text(out or "").replace("\n", "")
    if len(out) < 6 or out.startswith("{"):
        print(f"  [🧠 文案] 生成内容不合格被过滤: {out[:50]}...")
        return None
    return out[:400]


# ---------------------------------------------------------------------------
# 人设 / 文本生成
# ---------------------------------------------------------------------------
NICK_STYLES = [{"name": "纯英文短语", "desc": "1~3 个英文单词的小写短语", "examples": "midnight snacker"},
               {"name": "英文名+后缀", "desc": "英文昵称搭配数字等", "examples": "Cici_04"},
               {"name": "中英混排", "desc": "中文主体夹英文", "examples": "半糖de拿铁"},
               {"name": "短句状态", "desc": "口语状态", "examples": "今天也要早睡"},
               {"name": "食物+身份", "desc": "食物搭配身份", "examples": "冰美式续命中"},
               {"name": "极简符号", "desc": "极简组合", "examples": "404_"},
               {"name": "职业自嘲", "desc": "职业自嘲", "examples": "退堂鼓十级"},
               {"name": "新文艺意象", "desc": "冷意象", "examples": "雾岛听风"},
               {"name": "无厘头组合", "desc": "荒诞组合", "examples": "冰箱里的企鹅"},
               {"name": "拼音梗", "desc": "拼音缩写", "examples": "xswl本人"}]


def _normalize_nick(s: str) -> str: return re.sub(r"\s+", "", s or "").lower()


def _nick_acceptable(cand: str, used_norm: set) -> bool:
    if not re.fullmatch(r"[\w\u4e00-\u9fff·\-_.\s]{2,16}", cand): return False
    n = _normalize_nick(cand)
    if len(n) < 2: return False
    if any(b in cand for b in ("用户", "测试", "管理员", "{", "}")): return False
    for u in used_norm:
        if n == u: return False
        if len(u) >= 3 and (u in n or n in u): return False
    return True


def gen_persona(idx: int, used_nicks: list, state: dict) -> dict | None:
    provider = assign_llm_provider(state)
    if not provider:
        print("[警告] 所有已配置的有效 LLM Provider 均已达到容量上限，暂停生成新账号。", file=sys.stderr)
        return None
    provider_name = provider["name"]
    nat = random.choice(NATIONALITIES)
    used_norm = {_normalize_nick(n) for n in used_nicks if n}
    nick = ""
    for _ in range(5):
        style = random.choice(NICK_STYLES)
        used_show = "、".join(sorted(used_norm)[-40:]) or "（暂无）"
        raw = _clean_llm_text(llm_generate(
            f"你是一个活跃在社交网络的年轻用户，国籍是【{nat['country']}】，主要使用【{nat['prompt_lang']}】。\n请给自己取一个符合该国文化背景的网名，必须使用【{style['name']}】风格：{style['desc']}\n语气示例：{style['examples']}\n硬性要求：1. 长度 2~16 字符；必须主要使用 {nat['prompt_lang']}。2. 不得与以下已有网名重复或同构：{used_show}\n3. 只输出名字本身。",
            provider_name) or "")
        cand = raw.strip()[:16]
        if _nick_acceptable(cand, used_norm): nick = cand; break
    if not nick:
        nick = f"BoUser{idx:03d}"
        while not _nick_acceptable(nick, used_norm): nick = f"BoUser{idx:03d}-{random.randint(10, 99)}"

    bio, personality, occupation, income = "", "", "普通职员", "中"
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"网名「{nick}」，国籍【{nat['country']}】。请写一句 10~25 字的 {nat['prompt_lang']} 个人简介（Bio）。\n"
            f"同时，定义他/她的核心性格（如：热情/高冷/社恐）、现实中的具体职业（如：大厂程序员、独立摄影师、投行VP、便利店店员）、以及月收入水平（只能填：低、中、高）。\n"
            f"格式要求：严格以 JSON 格式返回，如：{{\"bio\": \"简介\", \"personality\": \"性格\", \"occupation\": \"职业\", \"income\": \"低/中/高\"}}",
            provider_name) or "")
        try:
            parsed = json.loads(raw)
            bio = parsed.get("bio", "")[:50]
            personality = parsed.get("personality", "普通")
            occupation = parsed.get("occupation", "普通职员")
            income = parsed.get("income", "中")
            if income not in ("低", "中", "高"): income = "中"
            if bio: break
        except Exception:
            if 2 <= len(raw.strip()) <= 60: bio = raw.strip()[:50]; personality = "随性"; break
    if not bio: bio, personality = f"{nat['prompt_lang']} user", "普通"

    avatar_desc = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"网名「{nick}」（{nat['country']}人，{bio}，职业：{occupation}）需要一张匹配其意象的网络头像。\n请提取最具象的意象，翻译成 1~4 个英文图片搜索关键词（逗号分隔）。只输出关键词本身。",
            provider_name) or "")
        if re.fullmatch(r"[a-z0-9 ,\-]{2,60}", raw.strip()): avatar_desc = raw.strip(); break

    return {"nickname": nick, "bio": bio, "avatar_desc": avatar_desc, "nationality": nat["country"],
            "language": nat["language"], "lang_code": nat["lang_code"], "prompt_lang": nat["prompt_lang"],
            "personality": personality, "occupation": occupation, "income": income,
            "interests": random.sample(list(INTEREST_KEYWORDS), k=random.randint(2, 4)),
            "llm_provider": provider_name}


def gen_text(kind: str, persona: dict, history: list | None = None, max_tokens: int = 200,
             mental_state: str = "normal") -> str | None:
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"
    mental_prompts = {
        "inferior": "（心理：自卑）你说话小心翼翼，缺乏自信，倾向于讨好别人，不敢表达强烈观点，多用'可能'、'也许'。",
        "arrogant": "（心理：自大）你充满优越感，喜欢凡尔赛、说教、指点江山。经常使用'其实'、'说白了'，喜欢反驳别人。",
        "depressed": "（心理：压抑）你感到疲惫、无力。文字充满丧文化和emo感，喜欢用省略号，表达无奈。"
    }
    mental_instruction = mental_prompts.get(mental_state, "")
    if kind == "post":
        if history:
            p = (
                    f"以下是社区用户「{persona['nickname']}」（{persona['nationality']}人，性格：{persona['personality']}，职业：{persona.get('occupation', '未知')}）的历史帖子：\n" + "\n".join(
                f"- {t}" for t in
                history) + f"\n{lang_req} {mental_instruction} 请综合历史文风，写一条新的 50~150 字动态，只输出正文。")
        else:
            p = (
                f"你扮演社区用户「{persona['nickname']}」（{persona['nationality']}人，性格：{persona['personality']}，职业：{persona.get('occupation', '未知')}）。{lang_req} {mental_instruction} 以他/她的口吻发一条社区动态，50~150字，只输出正文。")
    else:
        stance = persona.get("interaction_stance", "neutral")
        if mental_state == "arrogant": stance = "gentle_disagree"
        stance_prompt = {"supportive": "这次更倾向真诚支持、接住对方的话题。",
                         "gentle_disagree": "礼貌表达不同看法，或者带有优越感地进行说教/指点江山。",
                         "neutral": "保持自然交流。"}.get(stance, "保持自然交流。")
        relationship = persona.get("relationship_context", "")
        p = (
            f"你是社区用户「{persona['nickname']}」（性格：{persona['personality']}，职业：{persona.get('occupation', '未知')}）。{lang_req} {mental_instruction} {relationship}\n{stance_prompt}\n请针对下面这条帖子写一条 10~40 字的评论：\n{persona.get('target', '')}\n只输出评论。")
    provider_name = persona.get("llm_provider") or get_default_provider_name()
    out = ""
    for _ in range(3):
        raw_out = llm_generate(p, provider_name, max_tokens=max_tokens)
        if not raw_out: continue
        out = _clean_llm_text(raw_out).replace("\n", "")
        min_len = 10 if kind == "post" else 2
        if len(out) >= min_len and not out.startswith("{") and "```" not in out: return out[:400]
    return None


def get_dynamic_image_tags(persona: dict) -> str:
    prompt = f"你是 {persona.get('nationality', '未知')} 人，性格 {persona.get('personality', '普通')}。你准备发一条带图的帖子。请给出 1~2 个英文搜索关键词（用逗号分隔），用于搜索符合你心情的生活照。\n只输出英文关键词。"
    provider_name = persona.get("llm_provider") or get_default_provider_name()
    try:
        tags = _clean_llm_text(llm_generate(prompt, provider_name) or "").replace(" ", "")
        if re.match(r"^[a-zA-Z0-9,]+$", tags): return tags
    except Exception:
        pass
    return "daily life, aesthetic"


def fetch_post_history(acc: dict, limit: int = 8) -> list:
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    posts = (r or {}).get("data") or []
    return [p.get("text", "") for p in posts if isinstance(p, dict) and p.get("text")][-limit:]


def fetch_latest_posts(acc: dict, limit: int = 15) -> list:
    r = http_json("GET", "/posts/getAllPosts", params={"page": 1, "size": limit, "account": acc["account"]},
                  token=acc["token"])
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 本地浏览决策与 Bowall 浏览/停留数据上报
# ---------------------------------------------------------------------------
def _stable_interest_seed(acc: dict) -> int: return sum(
    (idx + 1) * ord(ch) for idx, ch in enumerate(str(acc.get("account") or acc.get("nickname") or "bot")))


def ensure_agent_interests(acc: dict, state: dict) -> list:
    interests = acc.get("interests")
    if not isinstance(interests, list) or not interests:
        cached = state.setdefault("accounts", {}).get(acc.get("nickname"), {})
        interests = cached.get("interests") if isinstance(cached, dict) else None
    if not isinstance(interests, list) or not interests:
        rng = random.Random(_stable_interest_seed(acc))
        interests = rng.sample(list(INTEREST_KEYWORDS), k=rng.randint(2, 4))
    interests = [str(tag) for tag in interests if tag in INTEREST_KEYWORDS][:4]
    if not interests: interests = ["life", "travel"]
    acc["interests"] = interests
    with state_lock:
        state.setdefault("accounts", {}).setdefault(acc["nickname"], {})["interests"] = interests
    mark_state_dirty()
    return interests


def estimate_expected_dwell_seconds(post: dict) -> float:
    text = str(post.get("text") or "")
    images = post.get("images") if isinstance(post.get("images"), list) else []
    return max(3.0, min(90.0, 3.0 + (len(text) + 11) // 12 + len(images) * 4))


def local_interest_score(acc: dict, state: dict, post: dict, following: set) -> float:
    text = str(post.get("text") or "")
    lowered = text.lower()
    author = str(post.get("account") or "")
    score = 0.18 + random.uniform(-0.07, 0.07)
    post_lang = detect_lang(text)
    agent_lang = acc.get("lang_code", "unknown")
    score += 0.23 if post_lang == agent_lang or agent_lang == "unknown" else -0.09
    interests = ensure_agent_interests(acc, state)
    matched = sum(1 for tag in interests if any(keyword in lowered for keyword in INTEREST_KEYWORDS[tag]))
    score += min(0.34, matched * 0.15)
    images = post.get("images") if isinstance(post.get("images"), list) else []
    if images and any(tag in interests for tag in ("travel", "food", "photo", "life")): score += 0.08
    relation = state.get("relationships", {}).get(acc.get("account"), {}).get(author, {})
    affinity = float(relation.get("affinity", 0) or 0)
    familiarity = float(relation.get("familiarity", 0) or 0)
    score += affinity * 0.20 + familiarity * 0.16
    if author in following: score += 0.12
    personality = str(acc.get("personality") or "")
    score += sum(bias for trait, bias in PERSONALITY_DWELL_BIAS.items() if trait in personality) * 0.25
    return max(0.02, min(0.98, score))


def choose_dwell_seconds(acc: dict, post: dict, interest_score: float) -> int:
    expected = estimate_expected_dwell_seconds(post)
    personality = str(acc.get("personality") or "")
    personality_bias = sum(bias for trait, bias in PERSONALITY_DWELL_BIAS.items() if trait in personality)
    if random.random() > interest_score * 0.70 + 0.20:
        dwell = random.uniform(1.0, min(5.0, expected * 0.35))
    else:
        dwell = expected * (0.38 + interest_score * 1.05 + personality_bias + random.uniform(-0.20, 0.25))
    return int(max(1, min(300, round(dwell))))


def report_post_view(acc: dict, post_id: str) -> bool:
    r = http_json("POST", f"/posts/{post_id}/view", token=acc["token"])
    return bool(r) and r.get("code") == 1


def report_post_dwell(acc: dict, post_id: str, session_id: str, dwell_seconds: int) -> bool:
    r = http_json("POST", f"/posts/{post_id}/dwell", {"sessionId": session_id, "seconds": int(dwell_seconds)},
                  token=acc["token"])
    return bool(r) and r.get("code") == 1


def weighted_sample_without_replacement(items: list, weights: list, count: int) -> list:
    pool = list(zip(items, weights))
    selected = []
    for _ in range(min(count, len(pool))):
        index = random.choices(range(len(pool)), weights=[item[1] for item in pool], k=1)[0]
        selected.append(pool.pop(index)[0])
    return selected


# ---------------------------------------------------------------------------
# 🌟 头像：从真实网络图库抓取 (Reddit / Picsum)
# ---------------------------------------------------------------------------
def fetch_avatar(nickname: str, keywords: str, state: dict):
    with state_lock:
        used = set(state.setdefault("used_avatar_urls", []))

    # 1. 优先尝试从 Reddit 真实人像/生活摄影子版块获取
    subreddits = ["Portraits", "selfie", "aww", "pics"]
    reddit_ua = {"User-Agent": "AiCommunityBot/1.0 (Educational Simulation Script)"}

    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=20"
        try:
            req = urllib.request.Request(url, headers=reddit_ua)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                img_url = post.get("url", "")
                if img_url.endswith((".jpg", ".jpeg", ".png")) and "i.redd.it" in img_url:
                    if img_url in used: continue
                    try:
                        blob = http_download(img_url, timeout=10)
                    except Exception:
                        continue
                    if _is_image_bytes(blob, "jpg") or _is_image_bytes(blob, "png"):
                        ext = "jpg" if _is_image_bytes(blob, "jpg") else "png"
                        with state_lock:
                            used.add(img_url)
                            state["used_avatar_urls"] = sorted(used)
                        mark_state_dirty()
                        return blob, f"{uuid.uuid4().hex}.{ext}", f"image/{ext}"
        except Exception:
            continue

    # 2. 终极真实摄影图片兜底: Picsum (基于 nickname seed 保证同一账号头像固定)
    seed = urllib.parse.quote(f"{nickname}-{keywords or 'community'}", safe="")
    url = f"https://picsum.photos/seed/{seed}/400/400"
    if url not in used:
        try:
            blob = http_download(url, timeout=10)
            if _is_image_bytes(blob, "jpg"):
                with state_lock:
                    used.add(url)
                    state["used_avatar_urls"] = sorted(used)
                mark_state_dirty()
                return blob, f"{uuid.uuid4().hex}.jpg", "image/jpeg"
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# 状态管理
# ---------------------------------------------------------------------------
def _load_json_object(path: str, label: str) -> dict:
    if not os.path.exists(path): return {}
    try:
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError as e:
        print(f"[警告] {label}文件已损坏 ({e})，正在自动备份并重建...", file=sys.stderr)
        backup_file = path + f".corrupt_{int(time.time())}"
        try:
            os.replace(path, backup_file)
        except Exception:
            pass
        return {}


def _atomic_write_json(path: str, value: dict, private: bool = False) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_file = path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, path)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load_state() -> dict:
    state = _load_json_object(STATE_FILE, "状态") or {"accounts": {}}
    state.setdefault("accounts", {})
    credentials = _load_json_object(CREDENTIALS_FILE, "凭据")
    legacy_sensitive_data = False
    for nickname, account in state["accounts"].items():
        if not isinstance(account, dict): continue
        stored = credentials.get(nickname)
        stored = stored if isinstance(stored, dict) else {}
        for field in SENSITIVE_ACCOUNT_FIELDS:
            if account.get(field) is not None: legacy_sensitive_data = True
            if stored.get(field) is not None: account[field] = stored[field]
    if legacy_sensitive_data:
        save_state(state)
        print(f"[安全] 已将账号凭据从 {STATE_FILE} 迁移到独立凭据文件", file=sys.stderr)
    return state


def save_state(state: dict) -> None:
    with state_lock:
        if "used_avatar_urls" in state: state["used_avatar_urls"] = state["used_avatar_urls"][-1000:]
        if "replied_comment_ids" in state: state["replied_comment_ids"] = state["replied_comment_ids"][-2000:]
        public_state = copy.deepcopy(state)
    credentials = {}
    for nickname, account in public_state.get("accounts", {}).items():
        if not isinstance(account, dict): continue
        private_fields = {}
        for field in SENSITIVE_ACCOUNT_FIELDS:
            value = account.pop(field, None)
            if value is not None: private_fields[field] = value
        if private_fields: credentials[nickname] = private_fields
    with _state_file_lock:
        try:
            _atomic_write_json(CREDENTIALS_FILE, credentials, private=True)
            _atomic_write_json(STATE_FILE, public_state)
        except Exception as e:
            print(f"[错误] 保存状态失败: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 长期关系记忆
# ---------------------------------------------------------------------------
RELATION_MAX_PEERS = 120


def _relationship_bucket(affinity: float, familiarity: float) -> str:
    if familiarity >= 0.75 and affinity >= 0.35: return "熟悉的朋友"
    if familiarity >= 0.45 and affinity <= -0.25: return "熟悉但意见不太一致的人"
    if affinity >= 0.35: return "印象不错的关注对象"
    if affinity <= -0.35: return "观点常有分歧的对象"
    if familiarity >= 0.35: return "有过几次互动的熟人"
    return "关注过但还不熟的人"


def _display_name_for(state: dict, account: str, fallback: str = "对方") -> str:
    for nickname, item in list(state.get("accounts", {}).items()):
        if isinstance(item, dict) and item.get("account") == account: return str(
            item.get("nickname") or nickname or fallback)
    return fallback


def _ensure_relation(state: dict, source: str, target: str, target_name: str) -> dict:
    with state_lock:
        relationships = state.setdefault("relationships", {})
        source_map = relationships.setdefault(source, {})
        relation = source_map.setdefault(target, {"name": target_name or "对方", "affinity": 0.0, "familiarity": 0.0,
                                                  "interactions": 0, "positive_interactions": 0, "disagreements": 0,
                                                  "last_event": "尚未互动", "last_topic": "", "updated_at": 0})
        if target_name: relation["name"] = target_name
        return relation


def relationship_context(state: dict, source: str, target: str, target_name: str) -> str:
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    familiarity = float(relation.get("familiarity", 0))
    name = relation.get("name") or target_name or "对方"
    bucket = _relationship_bucket(affinity, familiarity)
    last_topic = relation.get("last_topic") or "没有特别记忆"
    return (
        f"关系记忆：这是「{name}」。你们过去互动过 {relation.get('interactions', 0)} 次；你对 TA 的好感为 {affinity:.2f}，熟悉度为 {familiarity:.2f}，目前是“{bucket}”。最近一次互动：{relation.get('last_event', '尚未互动')}；关联话题：{last_topic}。请延续这段关系的语气。")


def choose_interaction_stance(state: dict, source: str, target: str, target_name: str) -> str:
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    if affinity <= -0.25 and random.random() < 0.55: return "gentle_disagree"
    if affinity >= 0.25 and random.random() < 0.75: return "supportive"
    return "neutral"


def record_relationship(state: dict, source: str, target: str, target_name: str, event: str, stance: str = "neutral",
                        topic: str = "") -> None:
    effects = {"like": (0.025, 0.035), "comment": (0.07, 0.12), "reply": (0.11, 0.16), "dm": (0.15, 0.20)}
    affinity_delta, familiarity_delta = effects.get(event, (0.02, 0.03))
    if stance == "gentle_disagree":
        affinity_delta = -0.06 if event == "comment" else -0.025
    elif stance == "supportive":
        affinity_delta += 0.04
    reverse_name = _display_name_for(state, source, "对方")
    with state_lock:
        outgoing = _ensure_relation(state, source, target, target_name)
        outgoing["affinity"] = round(max(-1, min(1, float(outgoing["affinity"]) + affinity_delta)), 3)
        outgoing["familiarity"] = round(max(0, min(1, float(outgoing["familiarity"]) + familiarity_delta)), 3)
        outgoing["interactions"] = int(outgoing["interactions"]) + 1
        outgoing["positive_interactions"] = int(outgoing["positive_interactions"]) + (stance != "gentle_disagree")
        outgoing["disagreements"] = int(outgoing["disagreements"]) + (stance == "gentle_disagree")
        outgoing["last_event"] = {"like": "点赞了对方的动态", "comment": "评论了对方的动态",
                                  "reply": "回复了对方的评论", "dm": "发送了私信"}.get(event, "产生了互动")
        outgoing["last_topic"] = topic[:80]
        outgoing["updated_at"] = int(time.time())
        incoming = _ensure_relation(state, target, source, reverse_name)
        incoming_delta = affinity_delta * (0.7 if stance != "gentle_disagree" else 0.5)
        incoming["affinity"] = round(max(-1, min(1, float(incoming["affinity"]) + incoming_delta)), 3)
        incoming["familiarity"] = round(max(0, min(1, float(incoming["familiarity"]) + familiarity_delta * 0.75)), 3)
        incoming["interactions"] = int(incoming["interactions"]) + 1
        incoming["positive_interactions"] = int(incoming["positive_interactions"]) + (stance != "gentle_disagree")
        incoming["disagreements"] = int(incoming["disagreements"]) + (stance == "gentle_disagree")
        incoming["last_event"] = {"like": "对方点赞了我的动态", "comment": "对方评论了我的动态",
                                  "reply": "对方回复了我的评论", "dm": "对方发来了私信"}.get(event, "对方与我互动")
        incoming["last_topic"] = topic[:80]
        incoming["updated_at"] = int(time.time())
        for acc_id in (source, target):
            relations = state.get("relationships", {}).get(acc_id, {})
            if len(relations) > RELATION_MAX_PEERS:
                oldest = sorted(relations, key=lambda key: relations[key].get("updated_at", 0))
                for account_id in oldest[:-RELATION_MAX_PEERS]: relations.pop(account_id, None)
    mark_state_dirty()


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
        if not account_id: deleted.append(nickname); continue
        if not token: continue
        response = http_json("GET", "/user/getUser", params={"account": account_id}, token=token)
        if isinstance(response, dict) and response.get("code") == 0 and "不存在" in str(
                response.get("msg", "")): deleted.append(nickname)
    for nickname in deleted: pool.pop(nickname, None)
    if deleted: save_state(state); print(f"[pool] 已清理 {len(deleted)} 个后端不存在的历史账号", file=sys.stderr)
    return len(deleted)


def _request_login(phone: str) -> dict | None:
    code = "".join(random.choices("0123456789", k=6))
    response = http_json("POST", "/user/login", {"phone": phone, "code": code, "randomNum": code})
    data = (response or {}).get("data")
    return data if isinstance(data, dict) else None


def rotate_account_tokens(state: dict) -> tuple[int, int]:
    with state_lock:
        accounts = [(nickname, dict(account)) for nickname, account in state.get("accounts", {}).items() if
                    isinstance(account, dict)]
    rotated = 0
    failed = 0
    for nickname, snapshot in accounts:
        phone = snapshot.get("phone")
        expected_account = snapshot.get("account")
        if not phone or not expected_account: failed += 1; continue
        data = _request_login(phone)
        user = (data or {}).get("user")
        user = user if isinstance(user, dict) else {}
        token = (data or {}).get("token")
        if not token or user.get("account") != expected_account: failed += 1; continue
        with state_lock:
            current = state.get("accounts", {}).get(nickname)
            if isinstance(current, dict):
                current["token"] = token
                current["token_issued_at"] = int(time.time())
        rotated += 1
        if rotated % 25 == 0: mark_state_dirty()
    flush_state(state, force=True)
    return rotated, failed


def login_agent(state: dict, nickname: str, dry_run: bool):
    account = state["accounts"].get(nickname)
    if account and account.get("token"):
        if dry_run or _verify_token(account["account"], account["token"]): return account
    phone = account.get("phone") if isinstance(account, dict) else None
    if account and not phone: return None
    phone = phone or "199" + "".join(random.choices("0123456789", k=8))
    if dry_run: return {"phone": phone, "account": "DRY-" + uuid.uuid4().hex[:8], "token": "dry-token",
                        "nickname": nickname}
    data = _request_login(phone) or {}
    token = data.get("token")
    user = data.get("user") or {}
    if not token: return None
    if account and user.get("account") != account.get("account"): return None
    acc = {"phone": phone, "account": user.get("account"), "token": token, "token_issued_at": int(time.time()),
           "nickname": nickname}
    with state_lock:
        state["accounts"][nickname] = acc
    mark_state_dirty()
    return acc


def setup_profile(acc: dict, persona: dict, state: dict, dry_run: bool) -> bool:
    nick = acc["nickname"]
    if dry_run: return True
    r = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
    _u = (r or {}).get("data")
    user = _u if isinstance(_u, dict) else {}
    if not user.get("account"): return False
    nickname = str(persona.get("nickname") or acc.get("nickname") or "").strip()
    if not nickname: nickname = f"BoUser-{user['account'][:8]}"

    def put_profile(av):
        payload = {"account": user["account"], "name": nickname, "sign": persona["bio"], "phone": user.get("phone"),
                   "avatar": av}
        return bool(http_json("PUT", "/user", payload, token=acc["token"], raise_on_error=True))

    avatar_url = user.get("avatar")
    if not avatar_url:
        img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""), state)
        if not img: return False
        data, fname, ctype = img
        up = http_multipart("POST", "/user/avatar", fields={"account": acc["account"]}, file_field="avatar",
                            filename=fname, file_bytes=data, content_type=ctype, token=acc["token"])
        avatar_data = (up or {}).get("data")
        new_avatar = avatar_data.get("avatar") if isinstance(avatar_data, dict) else None
        if not new_avatar: return False
        avatar_url = new_avatar
        with state_lock:
            state.setdefault("avatars", {})[persona["nickname"]] = new_avatar
        mark_state_dirty()
    try:
        if not put_profile(avatar_url): return False
    except ApiError:
        return False
    check = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
    _g = (check or {}).get("data")
    got = _g if isinstance(_g, dict) else {}
    if got.get("name") != nickname: return False
    log_action(acc, "PROFILE_SETUP", details=f"Name:{nickname}, Avatar:{bool(got.get('avatar'))}")
    return True


# ---------------------------------------------------------------------------
# 社交动作
# ---------------------------------------------------------------------------
def fetch_dm_history(my_acc: str, target_acc: str, token: str, limit: int = 5) -> list:
    r = http_json("GET", "/message/getMessage",
                  params={"senderAccount": my_acc, "recipientAccount": target_acc, "page": 1, "size": limit},
                  token=token)
    data = (r or {}).get("data")
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list): return [{"sender": m.get("senderAccount"), "content": m.get("content")} for m in
                                              records if isinstance(m, dict)]
    return []


def send_dm(my_acc: str, target_acc: str, content: str, token: str) -> bool:
    payload = {"senderAccount": my_acc, "recipientAccount": target_acc, "content": content}
    r = http_json("POST", "/message/sendMessage", payload, token=token)
    return bool(r) and r.get("code") == 1


def generate_dm_text(persona: dict, target_name: str, history: list, affinity: float) -> str:
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"
    history_text = "（暂无历史记录，这是你主动发起的搭讪）"
    if history:
        my_acc = persona.get("account", "")
        lines = []
        for msg in history:
            sender_name = "我" if msg["sender"] == my_acc else target_name
            lines.append(f"{sender_name}: {msg['content']}")
        history_text = "\n".join(lines)
    prompt = (
        f"你正在社交软件上和 {target_name} 私信聊天。你们的好感度极高（{affinity:.2f}），有一种灵魂伴侣/相见恨晚的感觉。\n"
        f"你的性格是：{persona.get('personality', '普通')}，人设：{persona.get('bio', '')}。\n{lang_req}\n"
        f"以下是你们的最近聊天记录：\n{history_text}\n\n"
        f"请以极度口语化、像真人微信聊天的方式回复对方，或者主动开启一个新话题（分享今天的一件小事、表达一点思念或暧昧）。\n"
        f"字数 10~60 字，可以带点 emoji，不要像写文章，只输出消息内容本身。")
    provider_name = persona.get("llm_provider") or get_default_provider_name()
    for _ in range(3):
        raw_out = llm_generate(prompt, provider_name, max_tokens=150)
        if not raw_out: continue
        out = _clean_llm_text(raw_out).replace("\n", " ")
        if 5 <= len(out) <= 100 and not out.startswith("{"): return out
    return "在干嘛呢？"


def check_is_following(my_acc: str, target_acc: str, token: str) -> bool:
    r = http_json("GET", "/fans/isfan", params={"account": target_acc, "fansAccount": my_acc}, token=token)
    if r and r.get("code") == 1:
        data = r.get("data")
        if isinstance(data, dict) and data: return True
        if isinstance(data, str) and data: return True
    return False


def toggle_follow(my_acc: str, target_acc: str, token: str) -> bool:
    r = http_json("POST", "/user/add", {"account": target_acc, "fansAccount": my_acc}, token=token)
    return bool(r) and r.get("code") == 1


def fetch_post_comments(post_id: str, acc: dict) -> list:
    r = http_json("GET", "/comments/getComments",
                  params={"postId": str(post_id), "page": 1, "size": 20},
                  token=acc["token"],
                  silent_404=True)
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


def check_and_reply_interactions(acc: dict, state: dict, dry_run: bool):
    nick = acc["nickname"]
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    my_posts = (r or {}).get("data") or []
    if not my_posts: return
    replied_ids = set(state.setdefault("replied_comment_ids", []))
    new_replies = []
    for post in my_posts[:5]:
        pid = post.get("id")
        if not pid: continue
        comments = fetch_post_comments(str(pid), acc)
        for cmt in comments:
            cmt_id = str(cmt.get("id") or cmt.get("commentId") or "")
            cmt_account = cmt.get("account")
            cmt_text = str(cmt.get("text") or cmt.get("comments") or "")
            if cmt_account and cmt_account != acc["account"] and cmt_id not in replied_ids and not cmt.get("parentId"):
                new_replies.append({"post_id": str(pid), "comment_id": cmt_id, "text": cmt_text, "author": cmt_account})
    if not new_replies: return
    personality = acc.get("personality", "普通")
    reply_chance = 0.9 if "热情" in personality or "话痨" in personality else 0.3 if "高冷" in personality or "社恐" in personality else 0.6
    for item in new_replies:
        time.sleep(random.uniform(1.0, 3.0))
        if random.random() > reply_chance: continue
        if dry_run: continue
        commenter_name = _display_name_for(state, item["author"], "这位评论者")
        stance = choose_interaction_stance(state, acc["account"], item["author"], commenter_name)
        reply_text = gen_text("comment", {**acc, "target": item["text"], "interaction_stance": stance,
                                          "relationship_context": relationship_context(state, acc["account"],
                                                                                       item["author"], commenter_name)},
                              mental_state="normal")
        if not reply_text: continue
        r = http_json("POST", "/comments/post",
                      {"postsId": item["post_id"], "account": acc["account"], "comments": reply_text,
                       "parentId": item["comment_id"], "replyToAccount": item["author"]}, token=acc["token"])
        if r and r.get("code") == 1:
            with state_lock:
                state.setdefault("replied_comment_ids", []).append(item["comment_id"])
            record_relationship(state, acc["account"], item["author"], commenter_name, "reply", stance, item["text"])
            log_action(acc, "REPLY", target=item["comment_id"],
                       details=f"Author:{commenter_name}, Text:{reply_text[:80]}")


def create_post(acc: dict, text: str, dry_run: bool):
    if dry_run: return "dry-post-id"
    r = http_json("POST", "/posts/post", {"account": acc["account"], "text": text}, token=acc["token"])
    if r and r.get("code") == 1: return r.get("data")
    return None


def create_post_with_images(acc: dict, text: str, images: list, dry_run: bool):
    pid = create_post(acc, text, dry_run)
    if not pid: return None
    for data, fname, ctype, _t in images:
        up = http_multipart("POST", "/image/post", fields={"account": acc["account"], "postId": pid},
                            file_field="images", filename=fname, file_bytes=data, content_type=ctype,
                            token=acc["token"])
        if not (up and up.get("code") == 1):
            http_json("DELETE", f"/posts/delete/{pid}", params={"account": acc["account"]}, token=acc["token"])
            return None
    return pid


def comment_post(acc: dict, post_id: str, text: str, target_account: str, dry_run: bool):
    if dry_run: return True
    r = http_json("POST", "/comments/post",
                  {"postsId": post_id, "account": acc["account"], "comments": text, "parentId": "",
                   "replyToAccount": target_account or ""}, token=acc["token"])
    return bool(r) and r.get("code") == 1


def like_post(acc: dict, post_id: str, dry_run: bool):
    if dry_run: return True
    r = http_json("POST", "/like", {"account": acc["account"], "postId": post_id}, token=acc["token"])
    return bool(r) and r.get("code") == 1


# ---------------------------------------------------------------------------
# 🌟 马太效应与心理异化系统
# ---------------------------------------------------------------------------
def update_account_reputation(acc: dict, state: dict):
    nick = acc["nickname"]
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    posts = (r or {}).get("data") or []
    total_views = sum(int(p.get("viewCount") or 0) for p in posts if isinstance(p, dict))
    total_likes = sum(int(p.get("likeCount") or 0) for p in posts if isinstance(p, dict))
    score = total_views * 0.05 + total_likes * 5.0
    with state_lock:
        acc_state = state.setdefault("accounts", {}).setdefault(nick, {})
        acc_state["reputation_score"] = score
        acc_state["total_views"] = total_views
        acc_state["total_likes"] = total_likes
    acc["reputation_score"] = score
    return score


def calculate_mental_state(acc: dict, reputation_score: float) -> str:
    income = acc.get("income", "中")
    occupation = acc.get("occupation", "")
    if income == "低" and reputation_score < 20:
        return "inferior"
    elif income == "高" and reputation_score > 100:
        return "arrogant"
    elif reputation_score < 20:
        if any(w in occupation for w in ["程序", "开发", "金融", "投行", "医生", "设计", "审计", "民工"]):
            return "depressed"
        elif income == "高":
            return "depressed"
    return "normal"


def get_post_probability_and_tier(acc: dict) -> tuple[float, str, int, int]:
    score = acc.get("reputation_score", 0)
    base_prob = SESSION_CFG["post"]
    if score >= 500:
        return min(0.60, base_prob + 0.40), "👑 大V", 9, 400
    elif score >= 100:
        return min(0.35, base_prob + 0.20), "🌟 活跃达人", 6, 300
    elif score >= 20:
        return min(0.20, base_prob + 0.10), "🌱 小萌新", 3, 200
    else:
        return base_prob, "👻 透明人", 2, 150


# ---------------------------------------------------------------------------
# 发帖与用户会话
# ---------------------------------------------------------------------------
def publish_a_post(acc: dict, state: dict, tier: str, max_imgs: int, llm_tokens: int, mental_state: str = "normal"):
    nick = acc["nickname"]
    if not ENABLE_EXTERNAL_POST_IMAGES:
        n_img = 0
    elif tier == "👑 大V":
        n_img = random.randint(max(4, max_imgs - 4), max_imgs)
    elif tier == "🌟 活跃达人":
        n_img = random.randint(1, max_imgs)
    else:
        # 🛠️ 修复：新号也保证至少发 1 张图，避免大量纯文本
        n_img = random.randint(1, max(max_imgs, 1))

    if n_img == 0:
        history = fetch_post_history(acc)
        content = gen_text("post", acc, history=history, max_tokens=llm_tokens, mental_state=mental_state)
        if not content: return None
        imgs = []
    else:
        search_tags = get_dynamic_image_tags(acc)
        got = pick_and_download_images(n_img, search_tags)
        if not got: return None
        _topic, desc, imgs = got
        content = gen_post_from_images(acc, desc, imgs, max_tokens=llm_tokens, mental_state=mental_state)
        if not content: return None
    pid = create_post_with_images(acc, content, imgs, False)
    if pid:
        log_action(acc, "POST", target=str(pid), details=f"Images:{len(imgs)}, Text:{content[:100]}")
    return pid


def simulate_user_session(acc: dict, state: dict, dry_run: bool, skip_profile_setup: bool = False):
    global _active_sessions_count
    nick = acc["nickname"]
    nat = acc.get('nationality', '未知')
    with _active_sessions_lock:
        _active_sessions_count += 1
        current_online = _active_sessions_count
    with state_lock:
        total_accounts = len(state.get("accounts", {}))
    log_action(acc, "SESSION_START", details=f"Nat:{nat}, Online:{current_online}/{total_accounts}")
    try:
        if dry_run: return
        with state_lock:
            needs_profile_setup = (not skip_profile_setup and
                                   not state["accounts"].get(nick, {}).get("profile_done"))
        if needs_profile_setup:
            time.sleep(random.uniform(3.0, 15.0))
            throttle_avatar()
            persona = {"nickname": nick, "bio": acc.get("bio", ""), "avatar_desc": acc.get("avatar_desc", ""),
                       "llm_provider": acc.get("llm_provider") or get_default_provider_name()}
            if setup_profile(acc, persona, state, False):
                interests = ensure_agent_interests(acc, state)
                with state_lock:
                    state["accounts"][nick]["profile_done"] = True
                    state["accounts"][nick]["bio"] = acc.get("bio", "")
                    state["accounts"][nick]["avatar_desc"] = acc.get("avatar_desc", "")
                    state["accounts"][nick]["personality"] = acc.get("personality", "普通")
                    state["accounts"][nick]["nationality"] = acc.get("nationality", "")
                    state["accounts"][nick]["language"] = acc.get("language", "")
                    state["accounts"][nick]["lang_code"] = acc.get("lang_code", "unknown")
                    state["accounts"][nick]["prompt_lang"] = acc.get("prompt_lang", "简体中文")
                    state["accounts"][nick]["interests"] = interests
                    state["accounts"][nick]["llm_provider"] = acc.get("llm_provider") or get_default_provider_name()
                mark_state_dirty()
        update_account_reputation(acc, state)
        post_prob, tier, max_imgs, llm_tokens = get_post_probability_and_tier(acc)
        mental_state = calculate_mental_state(acc, acc.get("reputation_score", 0))
        acc["current_mental_state"] = mental_state
        with state_lock:
            state["accounts"].setdefault(nick, {})["current_mental_state"] = mental_state
        mark_state_dirty()
        if mental_state == "depressed":
            post_prob *= 1.5
        elif mental_state == "inferior":
            post_prob *= 0.5
        posts = fetch_latest_posts(acc, limit=15)
        if not posts: return
        with state_lock:
            acc_state = state["accounts"].get(nick, {})
            already_following = set(acc_state.get("following", []))
        ensure_agent_interests(acc, state)
        scored_posts = []
        for post in posts:
            pauthor = str(post.get("account") or "")
            if not pauthor or pauthor == acc["account"]: continue
            score = local_interest_score(acc, state, post, already_following)
            scored_posts.append((post, max(0.05, score ** 1.6 + random.uniform(0.01, 0.12))))
        browse_count = min(random.randint(3, 8), len(scored_posts))
        browse = weighted_sample_without_replacement([item[0] for item in scored_posts],
                                                     [item[1] for item in scored_posts], browse_count)
        session_id = uuid.uuid4().hex
        for post in browse:
            pid = post.get("id")
            ptext = post.get("text", "")
            pauthor = post.get("account", "")
            if not pid or pauthor == acc["account"]: continue
            author_data = post.get("user") if isinstance(post.get("user"), dict) else {}
            author_name = author_data.get("name") or _display_name_for(state, pauthor, "这位作者")
            interest_score = local_interest_score(acc, state, post, already_following)
            view_probability = max(0.05, min(0.98, 0.12 + interest_score * 0.82 + random.uniform(-0.10, 0.10)))
            if random.random() > view_probability: continue
            if not report_post_view(acc, str(pid)): continue
            planned_dwell_seconds = choose_dwell_seconds(acc, post, interest_score)
            dwell_started_at = time.monotonic()
            time.sleep(planned_dwell_seconds * DWELL_TIME_SCALE)
            dwell_seconds = max(1, min(300, round(time.monotonic() - dwell_started_at)))
            report_post_dwell(acc, str(pid), session_id, dwell_seconds)
            log_action(acc, "VIEW_DWELL", target=str(pid),
                       details=f"Author:{author_name}, Interest:{interest_score:.2f}, Dwell:{dwell_seconds}s")
            personality = str(acc.get("personality") or "")
            relation = state.get("relationships", {}).get(acc["account"], {}).get(pauthor, {})
            affinity = float(relation.get("affinity", 0) or 0)
            like_probability = max(0.01, min(0.90, SESSION_CFG["like"] * (0.20 + interest_score * 1.45) + max(0,
                                                                                                              affinity) * 0.14 + (
                                                 0.05 if "热情" in personality else 0)))
            read_depth = dwell_seconds / max(1.0, estimate_expected_dwell_seconds(post))
            comment_probability = max(0.005, min(0.70,
                                                 SESSION_CFG["comment"] * (0.12 + interest_score * 1.80) * max(0.18,
                                                                                                               min(1.25,
                                                                                                                   read_depth)) + max(
                                                     0, affinity) * 0.10 + (0.06 if any(
                                                     word in personality for word in ("话痨", "热情", "幽默")) else 0)))
            if mental_state == "inferior":
                comment_probability *= 0.4;
                like_probability *= 1.2
            elif mental_state == "arrogant":
                comment_probability *= 1.8;
                like_probability *= 0.3
            elif mental_state == "depressed":
                comment_probability *= 0.2;
                like_probability *= 0.3
            if post.get("isLike") == 0 and random.random() < like_probability:
                if like_post(acc, pid, False):
                    record_relationship(state, acc["account"], pauthor, author_name, "like", "supportive", ptext)
                    log_action(acc, "LIKE", target=str(pid), details=f"Author:{author_name}")
                time.sleep(random.uniform(0.5, 1.5))
            if random.random() < comment_probability:
                stance = choose_interaction_stance(state, acc["account"], pauthor, author_name)
                c = gen_text("comment", {**acc, "target": ptext, "interaction_stance": stance,
                                         "relationship_context": relationship_context(state, acc["account"], pauthor,
                                                                                      author_name)},
                             mental_state=mental_state)
                if not c: continue
                if comment_post(acc, pid, c, pauthor, False):
                    record_relationship(state, acc["account"], pauthor, author_name, "comment", stance, ptext)
                    log_action(acc, "COMMENT", target=str(pid), details=f"Author:{author_name}, Text:{c[:80]}")
                time.sleep(random.uniform(2.0, 4.0))
        if random.random() < post_prob:
            publish_a_post(acc, state, tier, max_imgs, llm_tokens, mental_state)
            time.sleep(random.uniform(2.0, 5.0))
            check_and_reply_interactions(acc, state, False)
        else:
            if random.random() < 0.4: check_and_reply_interactions(acc, state, False)
        my_relations = state.get("relationships", {}).get(acc["account"], {})
        followed_count = 0
        for target_acc, relation in my_relations.items():
            if not target_acc or target_acc == acc["account"]: continue
            affinity = float(relation.get("affinity", 0))
            familiarity = float(relation.get("familiarity", 0))
            should_follow = (familiarity >= 0.4 and affinity >= 0.35) or (affinity >= 0.60)
            if should_follow and target_acc not in already_following:
                if not dry_run:
                    is_fan = check_is_following(acc["account"], target_acc, acc["token"])
                    if not is_fan:
                        if toggle_follow(acc["account"], target_acc, acc["token"]):
                            already_following.add(target_acc)
                            followed_count += 1
                            log_action(acc, "FOLLOW", target=target_acc)
                    else:
                        already_following.add(target_acc)
                else:
                    already_following.add(target_acc)
        with state_lock:
            state["accounts"].setdefault(nick, {})["following"] = list(already_following)
        mark_state_dirty()

        dm_sent_count = 0
        for target_acc, relation in my_relations.items():
            if not target_acc or target_acc == acc["account"]: continue
            affinity = float(relation.get("affinity", 0))
            target_name = relation.get("name", "对方")
            if affinity >= 0.80:
                with state_lock:
                    last_dm = state["accounts"].get(nick, {}).get(f"last_dm_{target_acc}", 0)
                if time.time() - last_dm > 600:
                    history = fetch_dm_history(acc["account"], target_acc, acc["token"], limit=5)
                    dm_text = generate_dm_text(acc, target_name, history, affinity)
                    if not dry_run:
                        if send_dm(acc["account"], target_acc, dm_text, acc["token"]):
                            with state_lock: state["accounts"].setdefault(nick, {})[
                                f"last_dm_{target_acc}"] = time.time()
                            dm_sent_count += 1
                            record_relationship(state, acc["account"], target_acc, target_name, "dm", "supportive",
                                                dm_text)
                            log_action(acc, "DM", target=target_acc, details=f"Recipient:{target_name}")
        if dm_sent_count > 0: mark_state_dirty()
    finally:
        with _active_sessions_lock:
            _active_sessions_count -= 1
            current_online = _active_sessions_count
        log_action(acc, "SESSION_END", details=f"OnlineLeft:{current_online}")


# ---------------------------------------------------------------------------
# 🌟 分层持续调度系统 (动态贪心版)
# ---------------------------------------------------------------------------
def get_scheduling_batch(state: dict, concurrent_limit: int) -> list:
    accounts = state.get("accounts", {})
    now = time.time()
    cooldown_seconds = 120
    vip, active, normal, silent = [], [], [], []
    for nick, acc in accounts.items():
        if not is_account_ready(nick): continue
        if not acc.get("account") or not acc.get("token") or str(acc.get("account", "")).startswith("DRY-"): continue
        if acc.get("status") == "error_suspended": continue
        if now - acc.get("last_online_at", 0) < cooldown_seconds: continue
        score = acc.get("reputation_score", 0)
        if score >= 500:
            vip.append(acc)
        elif score >= 100:
            active.append(acc)
        elif score >= 20:
            normal.append(acc)
        else:
            silent.append(acc)
    all_available = vip + active + normal + silent
    if not all_available: return []
    if concurrent_limit <= 5:
        random.shuffle(all_available)
        batch = all_available[:concurrent_limit]
    else:
        batch = []
        used_nicks = set()
        target_vip = min(len(vip), max(1, int(concurrent_limit * 0.4)))
        target_active = min(len(active), max(1, int(concurrent_limit * 0.3)))
        for acc in random.sample(vip, target_vip): batch.append(acc); used_nicks.add(acc["nickname"])
        for acc in random.sample(active, target_active): batch.append(acc); used_nicks.add(acc["nickname"])
        rest_limit = concurrent_limit - len(batch)
        if rest_limit > 0:
            rest_pool = [a for a in (normal + silent) if a["nickname"] not in used_nicks]
            random.shuffle(rest_pool)
            for acc in rest_pool[:rest_limit]: batch.append(acc); used_nicks.add(acc["nickname"])
        if len(batch) < concurrent_limit:
            for pool in [vip, active, normal, silent]:
                for acc in pool:
                    if acc["nickname"] not in used_nicks:
                        batch.append(acc);
                        used_nicks.add(acc["nickname"])
                        if len(batch) >= concurrent_limit: break
                if len(batch) >= concurrent_limit: break
    with state_lock:
        for acc in batch: state["accounts"][acc["nickname"]]["last_online_at"] = now
    mark_state_dirty()
    return batch


# ---------------------------------------------------------------------------
# 🌟 流式启动：后台账号工厂
# ---------------------------------------------------------------------------
def prepare_accounts_worker(args, state):
    try:
        print("🧹 [工厂] 正在检查 LLM Provider 配置...")
        available_provider_names = {p["name"] for p in get_available_providers()}
        for nick, acc in list(state.get("accounts", {}).items()):
            if acc.get("llm_provider") not in available_provider_names:
                prov = assign_llm_provider(state, allow_overflow=True)
                acc["llm_provider"] = prov["name"]
        save_state(state)

        pool = state.setdefault("accounts", {})
        existing = [n for n in pool.keys() if pool[n].get("account")]
        reuse = random.sample(existing, min(args.agents, len(existing))) if existing else []
        print(f"🔄 [工厂] 开始流式登录 {len(reuse)} 个老账号...")

        for idx, nick in enumerate(reuse, 1):
            if factory_stop_event.is_set(): break
            cached = pool[nick]
            acc = login_agent(state, nick, args.dry_run)
            if acc:
                acc["bio"] = cached.get("bio") or state.get("personas", {}).get(nick, "")
                acc["personality"] = cached.get("personality", "普通")
                acc["nationality"] = cached.get("nationality", "")
                acc["language"] = cached.get("language", "")
                acc["lang_code"] = cached.get("lang_code", "unknown")
                acc["prompt_lang"] = cached.get("prompt_lang", acc.get("language") or "简体中文")
                acc["interests"] = cached.get("interests", [])
                acc["occupation"] = cached.get("occupation", "普通职员")
                acc["income"] = cached.get("income", "中")
                acc["llm_provider"] = cached.get("llm_provider") or get_default_provider_name()
                ensure_agent_interests(acc, state)
                mark_account_ready(nick)
                print(f"✅ [工厂] [{idx}/{len(reuse)}] {nick} 已登录，可立即调度")
            else:
                print(f"⚠️ [工厂] [{idx}/{len(reuse)}] {nick} 登录失败，本次启动不调度", file=sys.stderr)
            if factory_stop_event.wait(args.interval): break

        print("✅ [工厂] 老账号登录遍历完成，进入自然增长循环")
        while not factory_stop_event.is_set():
            active_count = ready_account_count()
            if active_count >= args.agents:
                factory_stop_event.wait(60)
                continue

            used_pool = list(state.get("accounts", {}).keys()) + list(state.get("personas", {}).keys())
            persona = gen_persona(0, used_pool, state)
            if not persona:
                factory_stop_event.wait(60)
                continue
            if persona["nickname"] in state.get("accounts", {}):
                factory_stop_event.wait(1)
                continue

            state.setdefault("personas", {})[persona["nickname"]] = persona["bio"]
            acc = login_agent(state, persona["nickname"], args.dry_run)
            if not acc:
                factory_stop_event.wait(5)
                continue
            acc["bio"] = persona["bio"]
            acc.update({key: persona.get(key) for key in
                        ("personality", "nationality", "language", "lang_code", "prompt_lang", "interests",
                         "occupation", "income")})
            acc["llm_provider"] = persona.get("llm_provider") or get_default_provider_name()
            ensure_agent_interests(acc, state)
            mark_account_ready(persona["nickname"])
            print(f"✨ [工厂] 新账号 {persona['nickname']} 已登录，可立即调度")
            factory_stop_event.wait(random.uniform(20, 60))

    except Exception as e:
        print(f"🚨 [工厂] 致命错误导致工厂线程崩溃: {e}", file=sys.stderr)
        traceback.print_exc()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="AI 社区模拟机器人（多模型负载均衡版 V3.2-RealImages）")
    ap.add_argument("--agents", type=int, default=300, help="目标账号池总数")
    ap.add_argument("--concurrent", type=int, default=60, help="同时在线人数")
    ap.add_argument("--like-chance", type=float, default=0.40)
    ap.add_argument("--comment-chance", type=float, default=0.15)
    ap.add_argument("--post-chance", type=float, default=0.10)
    ap.add_argument("--no-avatar", action="store_true", help="跳过资料/头像设置")
    ap.add_argument("--interval", type=float, default=0.5, help="老号登录间隔")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--rotate-tokens", action="store_true", help="启动前重新签发所有账号令牌")
    ap.add_argument("--rotate-tokens-only", action="store_true", help="只轮换账号令牌，完成后退出")
    args = ap.parse_args()

    SESSION_CFG.update({"like": args.like_chance, "comment": args.comment_chance, "post": args.post_chance})
    state = load_state()

    if args.rotate_tokens or args.rotate_tokens_only:
        rotated, failed = rotate_account_tokens(state)
        if args.rotate_tokens_only: return

    valid_providers = get_available_providers()
    if not valid_providers:
        print("[致命] 必须至少为一个 AI 模型配置 name/url/key/model。", file=sys.stderr)
        os._exit(1)

    with _ready_accounts_lock:
        _ready_account_names.clear()
    _ready_accounts_changed.clear()

    factory_thread = threading.Thread(target=prepare_accounts_worker, args=(args, state), daemon=True)
    factory_thread.start()

    try:
        round_count = 0
        while True:
            round_count += 1

            # 🛡️ 清除标志位，准备接收新的 ready 信号
            _ready_accounts_changed.clear()

            batch = get_scheduling_batch(state, args.concurrent)

            if not batch:
                # 如果没有可用账号，挂起主线程，等待新账号 ready 信号（最多等 10 秒）
                # 一旦工厂线程调用 mark_account_ready，这里会立即被唤醒
                _ready_accounts_changed.wait(10)
                continue

            # 有可用账号，立即并发执行，不等待
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrent) as ex:
                futures = {
                    ex.submit(simulate_user_session, acc, state, args.dry_run, args.no_avatar): acc
                    for acc in batch
                }
                concurrent.futures.wait(futures.keys())

                error_accounts = []
                for future, acc in futures.items():
                    nick = acc.get("nickname", "Unknown")
                    exc = future.exception()
                    if exc is not None:
                        error_accounts.append(nick)
                        error_msg = f"{type(exc).__name__}: {str(exc)}"
                        log_action(agent=acc, action="SESSION_ERROR", target=nick, details=error_msg, level="ERROR")
                        with state_lock:
                            acc_state = state["accounts"].get(nick, {})
                            acc_state["error_count"] = acc_state.get("error_count", 0) + 1
                            if acc_state["error_count"] >= 3:
                                acc_state["status"] = "error_suspended"
                if error_accounts: mark_state_dirty()

            # 异步保存状态
            flush_state(state, force=False)

            # 🚀 动态休眠策略：彻底解决“必须等登录完”的阻塞感
            active_count = ready_account_count()
            if active_count < args.agents:
                # 【登录阶段】：还有账号在登录，主循环只需短暂休眠 (2~5秒)
                # 这样能极快地轮转，一旦有新账号 ready，下一轮循环立刻就能抓到它并调度
                time.sleep(random.uniform(2.0, 5.0))
            else:
                # 【稳定阶段】：所有目标账号均已就绪，恢复正常的社区轮次间隔 (30~60秒)
                # 避免过于频繁的请求给后端或 LLM API 造成压力
                time.sleep(random.uniform(30.0, 60.0))

    except KeyboardInterrupt:
        print("\n\n🛑 [系统] 收到停止指令，正在通知工厂停工并保存状态...")
        factory_stop_event.set()
        flush_state(state, force=True)
        print("👋 赛博社区已停止运转。")


if __name__ == "__main__":
    main()