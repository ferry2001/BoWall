#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 社区模拟机器人（多模型负载均衡 & 自然增长 & 流式启动 & 终极整合版 V4.0-RealLife）
核心进化：
1. 彻底抛弃精修商业图库，转向 Reddit 真实生活/旅游/手机摄影板块，获取“游客打卡/随手拍”质感。
2. 引入“后台低频大批量进货 + 本地画廊 AI 策展 + 发完删废片”机制，完美复刻人类发朋友圈行为。
3. 保留所有 V3.x 神级架构：RLock防死锁、防抖写盘、Future异常熔断、动态贪心调度、静默404、全量控制台日志。
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

# 🌟 控制台全量打印所有行为事件
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)-7s] %(agent)-15s: %(message)s"))
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
    if details: msg += f" | Details: {details}"
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


def mark_account_ready(nickname: str) -> None:
    with _ready_accounts_lock: _ready_account_names.add(nickname)
    _ready_accounts_changed.set()


def is_account_ready(nickname: str) -> bool:
    with _ready_accounts_lock: return nickname in _ready_account_names


def ready_account_count() -> int:
    with _ready_accounts_lock: return len(_ready_account_names)


_api_cache_lock = threading.Lock()
_api_cache = {}
_image_download_lock = threading.Lock()
_last_image_download_ts = [0.0]
IMAGE_DOWNLOAD_MIN_GAP = float(os.environ.get("BOT_IMG_GAP", "0.2"))  # 稍微加快点下载速度
DWELL_TIME_SCALE = max(0.01, float(os.environ.get("BOT_DWELL_TIME_SCALE", "1.0")))
ENABLE_EXTERNAL_POST_IMAGES = os.environ.get("BOT_ENABLE_EXTERNAL_POST_IMAGES", "true").lower() in {"1", "true", "yes",
                                                                                                    "on"}


def throttle_image_download():
    with _image_download_lock:
        now = time.time()
        wait = IMAGE_DOWNLOAD_MIN_GAP - (now - _last_image_download_ts[0])
        if wait > 0: time.sleep(wait)
        _last_image_download_ts[0] = time.time()


BASE = os.environ.get("BOWALL_BASE", "http://localhost:8080")
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

state_lock = threading.RLock()
avatar_lock = threading.Lock()
_last_avatar_ts = [0.0]
AVATAR_MIN_GAP = float(os.environ.get("BOT_AVATAR_GAP", "5"))


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
    with _state_dirty_lock: _state_revision += 1


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


SESSION_CFG = {"like": 0.10, "comment": 0.05, "post": 0.02}

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

# ---------------------------------------------------------------------------
# 生活事件与发帖意图（V4.1）
# 事件、表达方式和是否配图均在本地决定；LLM 只把既定事件写成自然的话。
# ---------------------------------------------------------------------------
LIFE_EVENT_POOLS = {
    "work": [("临下班突然收到一个新任务", "annoyed", .55), ("解决了一个困扰自己很久的问题", "excited", .65),
             ("今天工作状态特别差，效率很低", "tired", .40), ("摸鱼的时候突然有了一个不错的想法", "excited", .45)],
    "study": [("今天终于搞懂了一个之前一直没弄明白的问题", "excited", .60), ("坐下来半小时什么都没学进去", "annoyed", .35),
              ("本来只想看十分钟，结果学了两个小时", "satisfied", .45), ("今天的学习计划只完成了一半", "tired", .30)],
    "food": [("随便进的一家小店意外很好吃", "excited", .55), ("今天的外卖踩雷了", "annoyed", .40),
             ("突然特别想吃小时候经常吃的东西", "nostalgic", .40), ("点的东西比照片看起来小了一半", "amused", .40)],
    "weather": [("出门以后突然开始下雨，而且没带伞", "annoyed", .45), ("今天傍晚的天空特别好看", "relaxed", .50),
                ("下了一整天的雨", "tired", .30), ("晚上突然变得很凉快", "relaxed", .30)],
    "social": [("很久没联系的朋友突然发来了消息", "happy", .55), ("和朋友聊了一个多小时废话", "happy", .40),
               ("本来约好的人临时有事取消了", "disappointed", .45), ("群里突然开始讨论一个很离谱的话题", "amused", .35)],
    "shopping": [("纠结很久的东西终于下单了", "excited", .40), ("发现昨天买的东西今天就降价了", "annoyed", .50),
                 ("买了一个完全不在计划里的东西", "amused", .35)],
    "home": [("收拾房间时翻出了以前的东西", "nostalgic", .45), ("本来准备收拾房间，最后躺床上玩手机了", "amused", .35),
             ("今天什么都不想干，只想待在家里", "tired", .25), ("终于把拖了很久的小事处理掉了", "satisfied", .35)],
    "internet": [("刷到一个特别离谱的帖子", "amused", .35), ("发现一个很好用的网站或者工具", "excited", .50),
                 ("看到一个观点，想了半天还是不同意", "annoyed", .45), ("无意间翻到了自己几年前发的东西", "nostalgic", .45)],
    "exercise": [("今天运动状态比预想中好很多", "excited", .50), ("本来不想运动，最后还是去了", "satisfied", .40),
                 ("练完以后感觉整个人清醒了", "relaxed", .40), ("今天运动的时候完全没状态", "tired", .30)],
    "travel": [("路过一个以前没去过的地方，意外停留了很久", "relaxed", .45), ("出门的路上比预计堵了很久", "annoyed", .30)],
    "random": [("今天突然想把手机关一会儿", "tired", .20), ("发生了一件很小但让人开心的事", "happy", .30)],
}

OCCUPATION_EVENT_BIAS = {
    "程序": {"work": 5, "internet": 3, "study": 2}, "开发": {"work": 5, "internet": 3},
    "学生": {"study": 5, "food": 2, "social": 2}, "教师": {"work": 4, "study": 3},
    "设计": {"work": 4, "shopping": 2, "internet": 2}, "摄影": {"travel": 3, "weather": 3},
    "医生": {"work": 5, "home": 2}, "销售": {"work": 5, "social": 3},
}

EVENT_IMAGE_PROBABILITY = {"photo": .25, "share": .10, "story": .08, "moment": .05, "achievement": .08,
                           "complaint": .02, "observation": .03, "question": .01, "opinion": .01, "random": .02}

REPLY_INTENT_WEIGHTS = {"agree": .16, "tease": .12, "ask_detail": .14, "own_experience": .14,
                        "disagree": .08, "clarify": .08, "emotional_reaction": .10, "short_reaction": .08,
                        "continue_topic": .07, "inside_joke": .03}
REPLY_INTENT_CONFIG = {
    "agree": ("3~35字", "表达认同，但不要复述对方的话。"), "tease": ("3~40字", "轻松调侃，不要恶意攻击。"),
    "ask_detail": ("5~45字", "对一个具体细节自然追问。"), "own_experience": ("10~80字", "若自然相关，可顺手提自己的类似经历；不要抢话题。"),
    "disagree": ("8~70字", "自然表达不同意见，不要长篇辩论。"), "clarify": ("5~70字", "补充或解释自己原来的意思。"),
    "emotional_reaction": ("2~30字", "表达第一反应，不需要完整论证。"), "short_reaction": ("1~15字", "极短，可使用语气词。"),
    "continue_topic": ("8~70字", "顺着当前话题自然延伸，不要突然升华。"), "inside_joke": ("2~35字", "像熟人说话，可以带一点接梗。"),
}
LOCAL_SHORT_REPLIES = {"amused": ["哈哈哈哈", "笑死", "绷不住了", "离谱", "草"],
                       "agree": ["确实", "真的", "是这样的", "+1", "同感"],
                       "sympathy": ["惨", "太惨了", "心疼你一秒"]}

# V4.2 本地评论理解：关键词仅用于行为决策，绝不增加模型调用。
COMMENT_EMOTION_KEYWORDS = {
    "amused": ["哈哈", "hhh", "lol", "笑死", "绷不住", "😂", "🤣"], "agree": ["确实", "真的", "没错", "同意", "赞同", "+1", "同感"],
    "disagree": ["不一定", "不同意", "不是吧", "不对", "未必", "不能这么说"], "surprised": ["真的假的", "不会吧", "这么离谱", "卧槽", "居然", "啊？", "震惊"],
    "sympathy": ["太惨了", "惨", "心疼", "可怜", "辛苦了", "抱抱"], "annoyed": ["无语", "服了", "烦死", "恶心", "气死", "受不了", "什么鬼"],
    "curious": ["好奇", "想知道", "然后呢", "后来呢", "怎么做到", "求问"], "supportive": ["加油", "支持", "厉害", "牛", "不错", "恭喜", "666"],
}
QUESTION_TYPE_KEYWORDS = {
    "reason": ["为什么", "为啥", "怎么会", "什么原因", "咋回事"], "method": ["怎么做", "怎么弄", "怎么搞", "怎么办", "如何", "有方法吗"],
    "result": ["后来呢", "然后呢", "最后呢", "结果呢", "解决了吗", "成了吗"], "opinion": ["你觉得", "你怎么看", "你认为", "你会选"],
    "price": ["多少钱", "多少块", "价格", "贵吗", "便宜吗"], "location": ["哪里", "哪家", "在哪", "什么地方", "哪个店"],
    "time": ["什么时候", "几点", "多久", "多长时间", "哪天"], "identity": ["谁", "哪个人", "什么人", "谁啊"],
    "object": ["什么", "哪个", "哪一个", "啥"], "experience": ["你也遇到过", "你遇到过吗", "你经历过吗", "以前有过吗"],
}
TOPIC_KEYWORDS = {
    "work": ["上班", "工作", "公司", "老板", "领导", "同事", "加班", "工资", "项目", "需求", "客户", "会议", "下班"],
    "study": ["学习", "考试", "作业", "老师", "学生", "学校", "论文", "复习", "成绩", "课程", "毕业"],
    "food": ["吃", "饭", "外卖", "餐厅", "咖啡", "奶茶", "火锅", "早餐", "午饭", "晚饭", "好吃", "难吃"],
    "commute": ["地铁", "公交", "打车", "堵车", "开车", "通勤", "车站", "高铁", "出租车"],
    "exercise": ["健身", "训练", "跑步", "卧推", "深蹲", "硬拉", "运动", "健身房", "散步"],
    "technology": ["ai", "人工智能", "电脑", "手机", "程序", "代码", "bug", "软件", "网站", "app", "模型", "服务器"],
    "money": ["钱", "工资", "收入", "价格", "贵", "便宜", "赚钱", "亏", "涨价", "降价"],
    "relationship": ["对象", "男朋友", "女朋友", "前任", "恋爱", "喜欢", "分手", "约会"], "friendship": ["朋友", "室友", "兄弟", "闺蜜", "同学", "群聊"],
    "family": ["爸", "妈", "父母", "家里", "家人", "爷爷", "奶奶"], "weather": ["天气", "下雨", "下雪", "太阳", "热", "冷", "风", "温度"],
    "shopping": ["买", "下单", "购物", "淘宝", "京东", "快递", "包裹", "退货", "退款"], "internet": ["网上", "帖子", "评论", "视频", "热搜", "微博", "抖音", "小红书", "reddit", "推特"],
    "travel": ["旅游", "旅行", "酒店", "景点", "机场", "飞机", "海边", "爬山", "出差"],
}
EVENT_CATEGORY_TOPIC_MAP = {"work": {"work"}, "study": {"study"}, "food": {"food"}, "commute": {"commute"},
                            "exercise": {"exercise"}, "internet": {"internet", "technology"}, "shopping": {"shopping", "money"},
                            "weather": {"weather"}, "social": {"friendship", "relationship"}, "home": {"family"}, "travel": {"travel"}}

_DEFAULT_PROVIDERS = [
    {
        "name": "deepseek", "url": os.environ.get("BOT_DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"),
        "key": os.environ.get("BOT_DEEPSEEK_KEY", os.environ.get("BOT_LLM_KEY", "")),
        "model": os.environ.get("BOT_DEEPSEEK_MODEL", "deepseek-chat"),
        "vlm_url": os.environ.get("BOT_VLM_URL", ""), "vlm_key": os.environ.get("BOT_VLM_KEY", ""),
        "vlm_model": os.environ.get("BOT_VLM_MODEL", ""),
        "capacity": 10000, "semaphore": threading.Semaphore(30)  # 🛠️ 扩容至 1万，并发锁提升至 50
    },
    {
        "name": "qwen",
        "url": os.environ.get("BOT_QWEN_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        "key": os.environ.get("BOT_QWEN_KEY", ""), "model": os.environ.get("BOT_QWEN_MODEL", "qwen-plus"),
        "vlm_url": os.environ.get("BOT_QWEN_VLM_URL",
                                  "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        "vlm_key": os.environ.get("BOT_QWEN_VLM_KEY", os.environ.get("BOT_QWEN_KEY", "")),
        "vlm_model": os.environ.get("BOT_QWEN_VLM_MODEL", "qwen-vl-max"),
        "capacity": 10000, "semaphore": threading.Semaphore(30)  # 🛠️ 扩容至 1万，并发锁提升至 50
    }
]
_env_providers = os.environ.get("BOT_LLM_PROVIDERS")
if _env_providers:
    try:
        LLM_PROVIDERS = json.loads(_env_providers)
        for p in LLM_PROVIDERS: p.setdefault("semaphore", threading.Semaphore(3)); p.setdefault("capacity", 30)
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
        if allow_overflow: return min(available, key=lambda p: counts[p["name"]] / max(1, int(p["capacity"])))
        return None


ALLOWED_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
NATIONALITIES = [
    {"country": "中国", "country_code": "CN", "language": "中文", "lang_code": "zh", "prompt_lang": "简体中文"},
    {"country": "美国", "country_code": "US", "language": "English", "lang_code": "en", "prompt_lang": "English"},
    {"country": "日本", "country_code": "JP", "language": "日本語", "lang_code": "ja", "prompt_lang": "日本語"},
    {"country": "韩国", "country_code": "KR", "language": "한국어", "lang_code": "ko", "prompt_lang": "한국어"},
    {"country": "法国", "country_code": "FR", "language": "Français", "lang_code": "fr", "prompt_lang": "Français"},
    {"country": "德国", "country_code": "DE", "language": "Deutsch", "lang_code": "de", "prompt_lang": "Deutsch"},
    {"country": "俄罗斯", "country_code": "RU", "language": "Русский", "lang_code": "ru", "prompt_lang": "Русский"},
    {"country": "西班牙", "country_code": "ES", "language": "Español", "lang_code": "es", "prompt_lang": "Español"},
]
LANGUAGE_PROMPT_NAMES = {item["lang_code"]: item["prompt_lang"] for item in NATIONALITIES}
EDUCATION_ENGLISH_BASE = {"primary": .05, "middle_school": .10, "high_school": .18,
                          "bachelor": .32, "master": .48, "phd": .58, "overseas": .82}
OCCUPATION_ENGLISH_BONUS = {"程序": .12, "开发": .12, "产品": .10, "设计": .07, "金融": .12,
                            "投行": .15, "咨询": .15, "外贸": .18, "翻译": .25, "教师": .08, "学生": .05}
INCOME_ENGLISH_BONUS = {"低": -.05, "中": 0, "高": .08}


def build_language_profile(country_code: str, native: str, education: str, occupation: str, income: str) -> dict:
    if native == "en": english_level = 1.0
    else:
        occupation_bonus = max((bonus for keyword, bonus in OCCUPATION_ENGLISH_BONUS.items() if keyword in occupation), default=0.0)
        english_level = min(.95, max(.01, EDUCATION_ENGLISH_BASE.get(education, .18) + occupation_bonus +
                                     INCOME_ENGLISH_BONUS.get(income, 0)))
    languages = {native: 1.0, "en": english_level}
    return {"country": country_code, "native": native, "education": education,
            "english_level": round(english_level, 3), "languages": languages}


def ensure_language_profile(acc: dict, state: dict) -> dict:
    cached = acc.get("language_profile")
    if isinstance(cached, dict) and cached.get("native") and isinstance(cached.get("languages"), dict): return cached
    nat = next((item for item in NATIONALITIES if item["country"] == acc.get("nationality")), None)
    country_code = acc.get("country_code") or (nat or {}).get("country_code", "")
    native = acc.get("lang_code") or (nat or {}).get("lang_code", "en")
    profile = build_language_profile(country_code, native, acc.get("education", "high_school"),
                                     acc.get("occupation", ""), acc.get("income", "中"))
    acc["country_code"], acc["education"], acc["language_profile"] = country_code, profile["education"], profile
    with state_lock:
        state.setdefault("accounts", {}).setdefault(acc["nickname"], {}).update(
            {"country_code": country_code, "education": profile["education"], "language_profile": profile})
    mark_state_dirty()
    return profile


def choose_comment_language(acc: dict, post_language: str) -> str | None:
    profile = acc.get("language_profile", {})
    native = profile.get("native", acc.get("lang_code", "zh"))
    ability = float(profile.get("languages", {}).get(post_language, 0) or 0)
    if post_language in ("unknown", native): return native
    if post_language == "en" and ability >= .35: return "en"
    if post_language == "en" and ability >= .20 and random.random() < ability: return "en"
    return post_language if ability >= .25 else None


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
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(
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
        if e.code == 404 and silent_404: return None
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
# 🌟 真实生活照/游客打卡 画廊引擎 (V4.0 核心)
# ---------------------------------------------------------------------------
GALLERY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gallery")
os.makedirs(GALLERY_DIR, exist_ok=True)

# 🎯 降频增批策略：每次下150张，然后休息10~30分钟
GALLERY_MIN_STOCK = 150
GALLERY_BATCH_SIZE = 120
GALLERY_FETCH_INTERVAL = (600, 1200)

# 🎯 专门针对“游客打卡/真实生活/手机随手拍”的搜索词
TOURIST_TAGS = [
    # 中国城市与生活 (英文标签在 Unsplash/Reddit 也能搜到部分)
    "shanghai street", "beijing cafe", "chongqing night", "guangzhou morning",
    "chinese tourist", "asian street food", "subway commute china", "high speed rail",

    # 亚洲日常烟火气 (Reddit/Unsplash 友好)
    "tokyo street", "seoul coffee shop", "osaka night", "asian morning routine",
    "chinese breakfast", "hotpot dinner", "bubble tea", "night market asia",

    # 通用但容易出亚洲面孔的标签
    "asian student", "chinese office worker", "korean fashion street", "japanese train",
    "chinese park morning", "taiwan night market", "asian family travel",

    # 保留部分高质量通用词作为调剂
    "sunset city", "rainy window", "messy desk", "cat sleeping", "book and coffee"
    "tourist photo", "vacation selfie", "landmark visit", "travel memory", "coffee shop visit",
    "restaurant food", "street view", "sunset photo", "hotel room", "airport waiting",
    "train station", "beach day", "museum visit", "shopping mall", "park walk", "city night",
    "morning routine", "messy desk", "lunch break", "weekend vibe", "rainy window",
    "subway commute", "cafe window", "cat sleeping", "book and coffee", "neon night"
]


def _is_image_bytes(data: bytes, ext: str) -> bool:
    if ext == "jpg": return data[:3] == b"\xff\xd8\xff"
    if ext == "png": return data[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == "gif": return data[:6] in (b"GIF87a", b"GIF89a")
    if ext == "webp": return data[:4] == b"RIFF" and len(data) > 11 and data[8:12] == b"WEBP"
    if data[:3] == b"\xff\xd8\xff": return True
    if data[:8] == b"\x89PNG\r\n\x1a\n": return True
    if data[:4] == b"RIFF" and len(data) > 11 and data[8:12] == b"WEBP": return True
    return False


def fetch_reddit_tourist_photos(query: str, n: int) -> list:
    """🌟 亚洲真实 UGC：专门抓取 Reddit 亚洲/中国相关的真实生活板块"""
    asian_subreddits = [
        "China", "Shanghai", "Beijing", "Chongqing", "Shenzhen",
        "JapanTravel", "Tokyo", "Korea", "Seoul", "AsianStreetFood",
        "ChineseLanguage", "TravelChina", "Taiwan", "Singapore"
    ]
    # 随机选 2 个亚洲板块混合搜索
    subs = random.sample(asian_subreddits, 2)
    images = []

    for sub in subs:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=30"
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                img_url = post.get("url", "")
                title = post.get("title", "")
                if img_url.endswith((".jpg", ".jpeg", ".png", ".webp")) and "i.redd.it" in img_url:
                    mime = "image/webp" if img_url.endswith(".webp") else "image/jpeg"
                    images.append((img_url, mime, f"Reddit r/{sub}: {title[:30]}"))
                    if len(images) >= n: break
        except Exception:
            continue
    return images


def fetch_unsplash_source(query: str, n: int) -> list:
    """🌟 补充图源：Unsplash Source (生活化随机图)"""
    images = []
    for i in range(n):
        sig = uuid.uuid4().hex[:8]
        url = f"https://source.unsplash.com/800x600/?{urllib.parse.quote(query)}&sig={sig}"
        images.append((url, "image/jpeg", f"Unsplash: {query}"))
    return images


def fetch_picsum(n: int) -> list:
    """🌟 兜底图源：Picsum (保证绝对有图)"""
    images = []
    for _ in range(n):
        url = f"https://picsum.photos/800/600?random={random.randint(1, 999999)}"
        images.append((url, "image/jpeg", "Picsum random"))
    return images


def fetch_bing_cn_images(query: str, n: int) -> list:
    """🌟 核心本土图源：Bing 中文图片搜索 (获取真实中国人/中国街景的最佳途径)"""
    # 使用 cn.bing.com 获取中文搜索结果
    url = f"https://cn.bing.com/images/search?q={urllib.parse.quote(query)}&first=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # 提取 Bing 图片的真实 URL (murl 字段)
        pattern = re.compile(r'"murl":"(https://[^"]+)"')
        matches = pattern.findall(html)

        images = []
        seen_urls = set()
        for img_url in matches:
            clean_url = img_url.replace("\\u002F", "/").replace("\\", "")
            if clean_url not in seen_urls and any(
                    clean_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                # 过滤掉明显是图标或极小缩略图的链接
                if "thumb" not in clean_url and "small" not in clean_url:
                    images.append((clean_url, "image/jpeg", f"Bing-CN: {query}"))
                    seen_urls.add(clean_url)
                    if len(images) >= n: break

        if images:
            print(f"  [🇨🇳 Bing-CN] 成功获取 {len(images)} 张本土生活照")
        return images
    except Exception as e:
        print(f"  [⚠️ Bing-CN] 搜索失败: {e}")
        return []


def background_gallery_worker():
    """🌟 后台单线程：低频大批量从多平台进货，建立庞大的本地真实图库"""
    print("🖼️ [画廊] 真实生活照进货引擎已启动 (策略: 低频大批量 + 游客打卡风)...")
    while not factory_stop_event.is_set():
        try:
            current_files = [f for f in os.listdir(GALLERY_DIR) if os.path.isfile(os.path.join(GALLERY_DIR, f))]
            current_stock = len(current_files)

            if current_stock >= GALLERY_MIN_STOCK:
                wait_time = random.uniform(*GALLERY_FETCH_INTERVAL)
                print(f"💤 [画廊] 库存充足 ({current_stock}/{GALLERY_MIN_STOCK})，休眠 {int(wait_time / 60)} 分钟...")
                factory_stop_event.wait(wait_time)
                continue

            queries = random.sample(TOURIST_TAGS, 3)
            print(f"📥 [画廊] 库存告急 ({current_stock}/{GALLERY_MIN_STOCK})，开启多平台大批量进货: {queries}")

            all_urls = []
            for q in queries:
                all_urls.extend(fetch_bing_cn_images(q, 20))

                # 🌏 优先级 2：Reddit 亚洲板块 (真实亚洲网友 UGC)
                all_urls.extend(fetch_reddit_tourist_photos(q, 20))

                # 📸 优先级 3：Unsplash 亚洲标签 (高质量亚洲摄影)
                all_urls.extend(fetch_unsplash_source(q, 20))

                # 🎲 优先级 4：Picsum 兜底 (随机真实摄影)
                all_urls.extend(fetch_picsum(10))

                all_urls.extend(fetch_reddit_tourist_photos(q, 30))  # 主力：真实游客/生活照
                all_urls.extend(fetch_unsplash_source(q, 20))  # 补充：生活化随机图
                all_urls.extend(fetch_picsum(10))  # 兜底：随机摄影

            random.shuffle(all_urls)

            downloaded = 0
            for url, mime, title in all_urls:
                if downloaded >= GALLERY_BATCH_SIZE: break
                if url in _used_images_set: continue

                throttle_image_download()
                try:
                    data = http_download(url, timeout=10)
                    ext = "jpg"
                    if not _is_image_bytes(data, "jpg"):
                        if _is_image_bytes(data, "png"):
                            ext = "png"
                        elif _is_image_bytes(data, "webp"):
                            ext = "webp"
                        else:
                            continue

                    # 🎯 过滤掉太小的缩略图，保留真实手机拍的大小 (20KB ~ 3MB)
                    if len(data) < 20000 or len(data) > 3000000: continue

                    filepath = os.path.join(GALLERY_DIR, f"{uuid.uuid4().hex}.{ext}")
                    with open(filepath, "wb") as f:
                        f.write(data)
                    _used_images_set.add(url)
                    downloaded += 1
                except Exception:
                    continue

            print(f"✅ [画廊] 进货完成！成功入库 {downloaded} 张真实生活/游客照")
            wait_time = random.uniform(*GALLERY_FETCH_INTERVAL)
            factory_stop_event.wait(wait_time)
        except Exception as e:
            print(f"⚠️ [画廊] 进货异常: {e}")
            factory_stop_event.wait(300)


def image_content_type(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}" if ext in ("png", "webp", "gif") else "image/jpeg"


def clean_and_convert_gallery() -> None:
    """启动前统一相册扩展名，并在支持库就绪时转换 HEIC/HEIF。"""
    print("🧹 [画廊] 正在检查本地图片格式...")
    try:
        from PIL import Image
        import pillow_heif
        pillow_heif.register_heif_opener()
        heif_supported = True
    except ImportError:
        Image = None
        heif_supported = False
        print("⚠️ [画廊] 未安装 pillow-heif，已跳过 HEIC/HEIF 转换；可执行: pip install pillow pillow-heif")
    converted = renamed = failed = 0
    for filename in os.listdir(GALLERY_DIR):
        filepath = os.path.join(GALLERY_DIR, filename)
        if not os.path.isfile(filepath) or "." not in filename: continue
        stem, raw_ext = filename.rsplit(".", 1)
        ext = raw_ext.lower()
        if ext in ("heic", "heif"):
            if not heif_supported:
                continue
            try:
                new_filepath = os.path.join(GALLERY_DIR, f"{stem}.jpg")
                if os.path.exists(new_filepath): new_filepath = os.path.join(GALLERY_DIR, f"{stem}-{uuid.uuid4().hex[:8]}.jpg")
                with Image.open(filepath) as image:
                    image.convert("RGB").save(new_filepath, "JPEG", quality=85)
                os.remove(filepath)  # 仅在新 JPG 已成功保存后删除原始 HEIC。
                converted += 1
            except Exception as error:
                failed += 1
                print(f"  ⚠️ [画廊] 无法转换 {filename}: {error}")
        elif raw_ext != ext and ext in ("jpg", "jpeg", "png", "webp", "gif"):
            new_filepath = os.path.join(GALLERY_DIR, f"{stem}.{ext}")
            if not os.path.exists(new_filepath):
                try:
                    os.rename(filepath, new_filepath)
                    renamed += 1
                except OSError as error:
                    print(f"  ⚠️ [画廊] 无法重命名 {filename}: {error}")
    print(f"✅ [画廊] 格式检查完成：HEIC 转换 {converted} 张，扩展名规范化 {renamed} 张，失败 {failed} 张")


def ai_curate_gallery(persona: dict, image_paths: list, mental_state: str) -> tuple:
    """🌟 AI 策展：从本地画廊中挑选最符合心情的图片，并生成文案"""
    if not image_paths: return None, []
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"
    mental_prompts = {
        "inferior": "（心理：自卑）你拍照技术不好，倾向于选那些模糊的、边缘的、或者不起眼的角落照片。",
        "arrogant": "（心理：自大）你充满优越感，只选那些构图最完美、看起来最高级、最能炫耀你品味的照片。",
        "depressed": "（心理：压抑）你感到疲惫，倾向于选那些灰暗的、空旷的、或者带有孤独感的照片。",
        "normal": "（心理：平静）你正常挑选看起来最美观、最符合日常审美的照片。"
    }
    mental_instruction = mental_prompts.get(mental_state, mental_prompts["normal"])

    items = []
    for i, path in enumerate(image_paths):
        try:
            with open(path, "rb") as f:
                data = f.read()
            ctype = image_content_type(path)
            items.append((base64.b64encode(data).decode(), ctype, i))
        except Exception:
            continue
    if not items: return None, []

    prompt = (
        f"你是社区用户「{persona['nickname']}」。{lang_req} {mental_instruction}\n"
        f"你刚才出门拍了 {len(items)} 张照片（编号 0 到 {len(items) - 1}），现在准备发一条动态。\n"
        f"请从这些照片中，挑选出 {min(3, len(items))} 张最符合你当前心情和人设的照片。\n"
        f"【严格要求】：必须严格以 JSON 格式返回，不要包含任何 Markdown 标记或额外文字。\n"
        f"JSON 格式必须为：{{\"selected_indices\": [选中的图片编号列表], \"caption\": \"你写的 30~100 字帖子正文\"}}"
    )

    provider_name = persona.get("llm_provider") or get_default_provider_name()
    vlm_items = [(b64, ct) for b64, ct, _ in items]
    content = [{"type": "text", "text": prompt}]
    for b64, ctype in vlm_items: content.append(
        {"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}})

    prov = get_provider_config(provider_name)
    vlm_url = prov.get("vlm_url") or prov.get("url")
    vlm_key = prov.get("vlm_key") or prov.get("key")
    vlm_model = prov.get("vlm_model") or prov.get("model")

    if not (vlm_url and vlm_key):
        fallback_caption = llm_generate(f"你拍了照片，请写一条30字的朋友圈文案。{lang_req}", provider_name)
        return fallback_caption, [random.choice(image_paths)]

    payload = json.dumps({"model": vlm_model, "messages": [{"role": "user", "content": content}], "temperature": 1.0,
                          "max_tokens": 300}).encode("utf-8")
    try:
        req = urllib.request.Request(vlm_url, data=payload,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {vlm_key}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            raw_out = d["choices"][0]["message"]["content"].strip()
        cleaned = _clean_llm_text(raw_out)
        parsed = json.loads(cleaned)
        selected_indices = parsed.get("selected_indices", [0])
        caption = parsed.get("caption", "")
        selected_paths = [image_paths[i] for i in selected_indices if i < len(image_paths)]
        return caption, selected_paths
    except Exception as e:
        print(f"  [⚠️ 策展] AI 挑图失败: {e}")
        fallback_caption = llm_generate(f"你拍了照片，请写一条30字的朋友圈文案。{lang_req}", provider_name)
        return fallback_caption, [random.choice(image_paths)]


# ---------------------------------------------------------------------------
# 人设 / 文本生成 (保持原样)
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

    provider = assign_llm_provider(state, allow_overflow=True)
    if not provider:
        print("[警告] 没有可用的 LLM Provider，暂停生成新账号。", file=sys.stderr)
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
    education = random.choices(list(EDUCATION_ENGLISH_BASE), weights=[8, 18, 30, 28, 10, 3, 3], k=1)[0]
    language_profile = build_language_profile(nat["country_code"], nat["lang_code"], education, occupation, income)

    avatar_desc = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"网名「{nick}」（{nat['country']}人，{bio}，职业：{occupation}）需要一张匹配其意象的网络头像。\n请提取最具象的意象，翻译成 1~4 个英文图片搜索关键词（逗号分隔）。只输出关键词本身。",
            provider_name) or "")
        if re.fullmatch(r"[a-z0-9 ,\-]{2,60}", raw.strip()): avatar_desc = raw.strip(); break

    return {"nickname": nick, "bio": bio, "avatar_desc": avatar_desc, "nationality": nat["country"],
            "country_code": nat["country_code"], "language": nat["language"], "lang_code": nat["lang_code"], "prompt_lang": nat["prompt_lang"],
            "personality": personality, "occupation": occupation, "income": income,
            "education": education, "language_profile": language_profile,
            "interests": random.sample(list(INTEREST_KEYWORDS), k=random.randint(2, 4)),
            "llm_provider": provider_name, "social_anxiety": random.uniform(.1, .8), "fear_of_judgment": .2}


def _weighted_choice(mapping: dict) -> str:
    return random.choices(list(mapping), weights=[max(.01, value) for value in mapping.values()], k=1)[0]


def generate_local_life_event(acc: dict, state: dict) -> dict:
    """根据职业与兴趣本地抽取事件，并避免近期重复。"""
    weights = {category: 1.0 for category in LIFE_EVENT_POOLS}
    occupation = str(acc.get("occupation") or "")
    for keyword, bias in OCCUPATION_EVENT_BIAS.items():
        if keyword in occupation:
            for category, value in bias.items(): weights[category] = weights.get(category, 1.0) + value
    interest_categories = {"tech": "internet", "travel": "travel", "food": "food", "fitness": "exercise",
                           "life": "home", "books": "study", "photo": "weather"}
    for interest in ensure_agent_interests(acc, state):
        if interest in interest_categories: weights[interest_categories[interest]] += 1.5
    category = _weighted_choice(weights)
    recent = state.get("accounts", {}).get(acc["nickname"], {}).get("recent_life_events", [])
    seen = {item.get("description") for item in recent[-6:] if isinstance(item, dict)}
    pool = LIFE_EVENT_POOLS.get(category, LIFE_EVENT_POOLS["random"])
    candidates = [item for item in pool if item[0] not in seen] or pool
    description, mood, importance = random.choice(candidates)
    return {"category": category, "description": description, "mood": mood, "importance": importance,
            "occurred_at": datetime.now().isoformat(timespec="seconds")}


def build_post_intent(acc: dict, event: dict) -> dict:
    """本地决定发帖类型、长度和表达方式，不增加 LLM 调用。"""
    type_weights = {
        "annoyed": {"complaint": 5, "observation": 3, "opinion": 2}, "excited": {"share": 4, "achievement": 3, "moment": 2},
        "tired": {"moment": 4, "complaint": 3}, "amused": {"observation": 4, "story": 3}, "nostalgic": {"story": 5, "moment": 3},
        "relaxed": {"photo": 3, "moment": 4}, "happy": {"story": 4, "moment": 3}, "satisfied": {"achievement": 4, "moment": 3},
        "disappointed": {"complaint": 3, "moment": 3}, "surprised": {"story": 4, "question": 2},
    }
    post_type = _weighted_choice(type_weights.get(event["mood"], {"random": 1}))
    personality = str(acc.get("personality") or "")
    style = "口语化、像顺手发的一句话"
    if "幽默" in personality: style += "，可以带一点自嘲或玩笑"
    elif "高冷" in personality: style += "，克制简短"
    elif "话痨" in personality: style += "，可补充一两个具体细节"
    lower, upper = (15, 55) if event["importance"] < .4 else (30, 110)
    return {"post_type": post_type, "style": style, "min_length": lower, "max_length": upper}


def calculate_driving_force(event: dict, acc: dict) -> float:
    """计算生活事件带来的表达冲动；高兴或破防更容易突破评价恐惧。"""
    mood, importance = event.get("mood", "normal"), float(event.get("importance", .5) or .5)
    personality = str(acc.get("personality") or "")
    if mood in ("excited", "happy", "satisfied"):
        force = importance * 1.2 + .3 + (.2 if any(item in personality for item in ("热情", "话痨")) else 0)
    elif mood in ("annoyed", "disappointed", "depressed"):
        force = importance + .1 - (.1 if any(item in personality for item in ("内向", "社恐")) else 0)
    else:
        force = importance * .3
    return max(0.0, min(1.5, force))


def calculate_reply_driving_force(target_text: str, incoming_text: str, acc: dict, state: dict,
                                  target_acc: str) -> float:
    """计算在评论区发言的冲动：情绪刺激和关系都会提高表达欲。"""
    force = .20
    text = f"{target_text or ''} {incoming_text or ''}".lower()
    if any(word in text for word in ("哈哈", "笑死", "太棒了", "牛逼", "救命", "无语", "气死", "离谱", "绷不住")):
        force += .45
    relation = state.get("relationships", {}).get(acc["account"], {}).get(target_acc, {})
    affinity = float(relation.get("affinity", 0) or 0)
    if affinity > .4: force += .35
    elif affinity < -.2: force += .25
    return max(0.0, min(1.5, force))


def calculate_reply_fear_resistance(target_acc: str, is_own_post: bool, acc: dict, state: dict) -> float:
    """自己的帖子是主场；在陌生人的帖子下发言则有额外心理压力。"""
    resistance = float(acc.get("fear_of_judgment", .2) or .2) * (1 + float(acc.get("social_anxiety", .3) or .3))
    if is_own_post:
        resistance *= .4
    else:
        relation = state.get("relationships", {}).get(acc["account"], {}).get(target_acc, {})
        if float(relation.get("familiarity", 0) or 0) < .2: resistance *= 1.4
    if acc.get("current_mental_state") in ("inferior", "depressed"): resistance *= 1.6
    return resistance


def adjust_fear_of_judgment(acc: dict, state: dict, delta: float) -> float:
    """持久化互动后的心理反馈，并同步当前会话内存。"""
    with state_lock:
        account_state = state.setdefault("accounts", {}).setdefault(acc["nickname"], {})
        fear = min(1.0, max(0.0, float(account_state.get("fear_of_judgment", acc.get("fear_of_judgment", .2)) or .2) + delta))
        account_state["fear_of_judgment"] = round(fear, 3)
    acc["fear_of_judgment"] = round(fear, 3)
    mark_state_dirty()
    return fear


def generate_event_driven_post(acc: dict, state: dict, event: dict, intent: dict, mental_state: str,
                               max_tokens: int) -> str | None:
    recent = state.get("accounts", {}).get(acc["nickname"], {}).get("recent_life_events", [])[-3:]
    continuity = "；".join(item.get("description", "") for item in recent if isinstance(item, dict))
    mental_instruction = {"inferior": "语气稍微小心、缺乏自信", "arrogant": "语气带一点优越感但不要失礼",
                          "depressed": "语气疲惫、克制"}.get(mental_state, "自然平静")
    prompt = (
        f"你扮演社区用户「{acc['nickname']}」（性格：{acc.get('personality', '普通')}，职业：{acc.get('occupation', '未知')}）。"
        f"必须严格使用 {acc['prompt_lang']} 语言。\n刚发生的真实生活事件：{event['description']}；感受：{event['mood']}。\n"
        f"本地已决定这是 {intent['post_type']} 类型动态，表达方式：{intent['style']}，当前心理状态：{mental_instruction}。"
        f"请写 {intent['min_length']}~{intent['max_length']} 字正文，只输出正文。不要编造无关经历、标题或话题标签。"
    )
    if continuity: prompt += f"\n最近事件：{continuity}；如自然可有连续性，但不要重复叙述。"
    history = fetch_post_history(acc)
    if history: prompt += "\n参考既有文风：" + " / ".join(history[-4:])
    provider_name = acc.get("llm_provider") or get_default_provider_name()
    for _ in range(3):
        output = _clean_llm_text(llm_generate(prompt, provider_name, max_tokens=max_tokens) or "").replace("\n", "")
        if len(output) >= max(2, intent["min_length"] // 2) and not output.startswith("{"): return output[:400]
    return None


def remember_life_event(acc: dict, state: dict, event: dict) -> None:
    with state_lock:
        account_state = state.setdefault("accounts", {}).setdefault(acc["nickname"], {})
        account_state["recent_life_events"] = (account_state.setdefault("recent_life_events", []) + [dict(event)])[-30:]
    mark_state_dirty()


def curate_images_for_event(acc: dict, image_paths: list, event: dict, content: str, max_images: int = 3) -> list:
    """视觉模型只负责挑选和既定事件相符的照片，不能重写文案。"""
    # ️ 修复：VLM 接口通常有图片数量限制（如最多4张），先进行本地随机抽样
    vlm_candidates = image_paths
    if len(image_paths) > 4:
        vlm_candidates = random.sample(image_paths, 4)

    items = []
    for index, path in enumerate(vlm_candidates):
        try:
            with open(path, "rb") as f:
                data = f.read()
            items.append((base64.b64encode(data).decode(), image_content_type(path), index))
        except OSError:
            continue

    if not items: return []

    prompt = (f"从手机相册为动态选图。事件：{event['description']}。动态：{content}\n"
              f"候选图片编号 0 到 {len(items) - 1}。选择 0~{min(max_images, len(items))} 张最自然匹配的图片；"
              "不匹配就不要选，绝不为了带图强选。严格只返回 JSON：{\"selected_indices\":[0,1]}。")

    raw = llm_vision_generate([(b64, ctype) for b64, ctype, _ in items], prompt,
                              acc.get("llm_provider") or get_default_provider_name(), max_tokens=120)
    try:
        indices = json.loads(_clean_llm_text(raw or "{}")).get("selected_indices", [])
        indices = [index for index in indices if isinstance(index, int) and 0 <= index < len(items)]
        # 将 VLM 选中的抽样索引，映射回原始 image_paths 的真实索引
        original_indices = [vlm_candidates[index] for index in list(dict.fromkeys(indices))[:max_images]]
        # 找到这些图片在原始列表中的路径
        return [p for p in original_indices if p in image_paths]
    except (ValueError, TypeError, json.JSONDecodeError):
        # 🛠️ 如果 VLM 依然失败，降级为从原始列表中随机选 1 张，而不是放弃发图
        return [random.choice(image_paths)] if image_paths else []


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


MAX_SEEN_POST_IDS = 500
# UUID 帖子 ID 放在 GET 查询参数中；150 条约 5.5KB，可避开常见服务器的 URL 长度限制。
MAX_EXCLUDED_POST_IDS_PER_REQUEST = 150


def fetch_latest_posts(acc: dict, limit: int = 15, exclude_ids: list | None = None) -> list:
    params = {"page": 1, "size": limit, "account": acc["account"]}
    if exclude_ids:
        # 状态保留 500 条，但单次 GET 只传最近 150 条，避免 URL 过长。
        params["excludeIds"] = ",".join(
            str(post_id) for post_id in exclude_ids[-MAX_EXCLUDED_POST_IDS_PER_REQUEST:] if post_id)
    r = http_json("GET", "/posts/recommendations", params=params, token=acc["token"])
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
    if int(post.get("isFeatured") or post.get("is_featured") or 0): score += 0.28
    like_count = int(post.get("likeCount") or post.get("like_count") or 0)
    comment_count = int(post.get("commentCount") or post.get("comment_count") or 0)
    if like_count > 5 or comment_count > 3: score += 0.30
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
DEFAULT_AVATAR_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   "src", "main", "resources", "static", "assets", "me", "head-list.png")
AVATAR_RETRY_PROBABILITY = .20


def upload_avatar(acc: dict, data: bytes, filename: str, content_type: str) -> str | None:
    response = http_multipart("POST", "/user/avatar", fields={"account": acc["account"]}, file_field="avatar",
                              filename=filename, file_bytes=data, content_type=content_type, token=acc["token"])
    payload = (response or {}).get("data")
    return payload.get("avatar") if isinstance(payload, dict) and payload.get("avatar") else None


def upload_default_avatar(acc: dict) -> str | None:
    try:
        with open(DEFAULT_AVATAR_PATH, "rb") as avatar_file:
            return upload_avatar(acc, avatar_file.read(), "default-avatar.png", "image/png")
    except OSError as error:
        print(f"⚠️ [{acc['nickname']}] 默认头像不可用: {error}")
        return None


def fetch_avatar(nickname: str, keywords: str, state: dict):
    with state_lock:
        used = set(state.setdefault("used_avatar_urls", []))
    subreddits = ["Portraits", "selfie", "aww", "pics"]
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=20"
        try:
            req = urllib.request.Request(url, headers=UA)
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
                        with state_lock: used.add(img_url); state["used_avatar_urls"] = sorted(used)
                        mark_state_dirty()
                        return blob, f"{uuid.uuid4().hex}.{ext}", f"image/{ext}"
        except Exception:
            continue
    seed = urllib.parse.quote(f"{nickname}-{keywords or 'community'}", safe="")
    url = f"https://picsum.photos/seed/{seed}/400/400"
    if url not in used:
        try:
            blob = http_download(url, timeout=10)
            if _is_image_bytes(blob, "jpg"):
                with state_lock: used.add(url); state["used_avatar_urls"] = sorted(used)
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
        try:
            os.replace(path, path + f".corrupt_{int(time.time())}")
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
    return f"关系记忆：这是「{name}」。你们过去互动过 {relation.get('interactions', 0)} 次；你对 TA 的好感为 {affinity:.2f}，熟悉度为 {familiarity:.2f}，目前是“{bucket}”。最近一次互动：{relation.get('last_event', '尚未互动')}；关联话题：{last_topic}。请延续这段关系的语气。"


def choose_interaction_stance(state: dict, source: str, target: str, target_name: str) -> str:
    relation = _ensure_relation(state, source, target, target_name)
    affinity = float(relation.get("affinity", 0))
    if affinity <= -0.25 and random.random() < 0.55: return "gentle_disagree"
    if affinity >= 0.25 and random.random() < 0.75: return "supportive"
    return "neutral"


def record_relationship(state: dict, source: str, target: str, target_name: str, event: str, stance: str = "neutral",
                        topic: str = "") -> None:
    effects = {"like": (.02, .03), "comment": (.04, .06), "reply": (.06, .08),
               "dm_sent": (.01, .02), "dm_reply": (.08, .12)}
    affinity_delta, familiarity_delta = effects.get(event, (0.02, 0.03))
    if stance == "gentle_disagree":
        affinity_delta = -0.06 if event == "comment" else -0.025
    elif stance == "supportive":
        affinity_delta += 0.08
    reverse_name = _display_name_for(state, source, "对方")
    with state_lock:
        outgoing = _ensure_relation(state, source, target, target_name)
        outgoing["affinity"] = round(max(-1, min(1, float(outgoing["affinity"]) + affinity_delta)), 3)
        outgoing["familiarity"] = round(max(0, min(1, float(outgoing["familiarity"]) + familiarity_delta)), 3)
        outgoing["interactions"] = int(outgoing["interactions"]) + 1
        outgoing["positive_interactions"] = int(outgoing["positive_interactions"]) + (stance != "gentle_disagree")
        outgoing["disagreements"] = int(outgoing["disagreements"]) + (stance == "gentle_disagree")
        outgoing["last_event"] = {"like": "点赞了对方的动态", "comment": "评论了对方的动态",
                                  "reply": "回复了对方的评论", "dm_sent": "发送了私信", "dm_reply": "回复了私信"}.get(event, "产生了互动")
        outgoing["last_topic"] = topic[:80]
        outgoing["updated_at"] = int(time.time())
        incoming = _ensure_relation(state, target, source, reverse_name)
        incoming_delta = 0.0 if event == "dm_sent" else affinity_delta * (0.7 if stance != "gentle_disagree" else 0.5)
        incoming["affinity"] = round(max(-1, min(1, float(incoming["affinity"]) + incoming_delta)), 3)
        incoming_familiarity_delta = 0.0 if event == "dm_sent" else familiarity_delta * .75
        incoming["familiarity"] = round(max(0, min(1, float(incoming["familiarity"]) + incoming_familiarity_delta)), 3)
        incoming["interactions"] = int(incoming["interactions"]) + 1
        incoming["positive_interactions"] = int(incoming["positive_interactions"]) + (stance != "gentle_disagree")
        incoming["disagreements"] = int(incoming["disagreements"]) + (stance == "gentle_disagree")
        incoming["last_event"] = {"like": "对方点赞了我的动态", "comment": "对方评论了我的动态",
                                  "reply": "对方回复了我的评论", "dm_sent": "对方发来了私信", "dm_reply": "对方回复了私信"}.get(event, "对方与我互动")
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


def _request_login(phone: str, country_code: str = "") -> dict | None:
    code = "".join(random.choices("0123456789", k=6))
    response = http_json("POST", "/user/login", {"phone": phone, "code": code, "randomNum": code,
                                                     "country": country_code})
    data = (response or {}).get("data")
    return data if isinstance(data, dict) else None


def rotate_account_tokens(state: dict) -> tuple[int, int]:
    with state_lock:
        accounts = [(nickname, dict(account)) for nickname, account in state.get("accounts", {}).items() if
                    isinstance(account, dict)]
    rotated = 0;
    failed = 0
    for nickname, snapshot in accounts:
        phone = snapshot.get("phone");
        expected_account = snapshot.get("account")
        if not phone or not expected_account: failed += 1; continue
        data = _request_login(phone)
        user = (data or {}).get("user");
        user = user if isinstance(user, dict) else {}
        token = (data or {}).get("token")
        if not token or user.get("account") != expected_account: failed += 1; continue
        with state_lock:
            current = state.get("accounts", {}).get(nickname)
            if isinstance(current, dict): current["token"] = token; current["token_issued_at"] = int(time.time())
        rotated += 1
        if rotated % 25 == 0: mark_state_dirty()
    flush_state(state, force=True)
    return rotated, failed


def phone_for_country(country_code: str) -> str:
    prefix = {"CN": "+86", "US": "+1", "JP": "+81", "KR": "+82", "FR": "+33", "DE": "+49",
              "ES": "+34", "RU": "+7"}.get(country_code, "+86")
    return prefix + "".join(random.choices("0123456789", k=10))


def login_agent(state: dict, nickname: str, dry_run: bool, seed_profile: dict | None = None):
    account = state["accounts"].get(nickname)
    if account and account.get("token"):
        if dry_run or _verify_token(account["account"], account["token"]): return account
    phone = account.get("phone") if isinstance(account, dict) else None
    if account and not phone: return None
    country_code = (account or {}).get("country_code") or (seed_profile or {}).get("country_code", "CN")
    phone = phone or phone_for_country(country_code)
    if dry_run: return {"phone": phone, "account": "DRY-" + uuid.uuid4().hex[:8], "token": "dry-token",
                        "nickname": nickname}
    data = _request_login(phone, country_code) or {}
    token = data.get("token");
    user = data.get("user") or {}
    if not token: return None
    if account and user.get("account") != account.get("account"): return None
    acc = {"phone": phone, "account": user.get("account"), "token": token, "token_issued_at": int(time.time()),
           "nickname": nickname, "country_code": country_code}
    with state_lock:
        state["accounts"][nickname] = acc
    mark_state_dirty()
    return acc


def setup_profile(acc: dict, persona: dict, state: dict, dry_run: bool, try_remote_avatar: bool = True) -> bool:
    nick = acc["nickname"]
    if dry_run: return True
    r = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
    _u = (r or {}).get("data");
    user = _u if isinstance(_u, dict) else {}
    if not user.get("account"): return False
    nickname = str(persona.get("nickname") or acc.get("nickname") or "").strip()
    if not nickname: nickname = f"BoUser-{user['account'][:8]}"

    def put_profile(av):
        payload = {"account": user["account"], "name": nickname, "sign": persona["bio"], "phone": user.get("phone"),
                   "avatar": av, "country": acc.get("country_code"),
                   "nativeLanguage": acc.get("language_profile", {}).get("native", acc.get("lang_code")),
                   "englishLevel": acc.get("language_profile", {}).get("english_level")}
        return bool(http_json("PUT", "/user", payload, token=acc["token"], raise_on_error=True))

    avatar_url = user.get("avatar")
    if not avatar_url:
        img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""), state) if try_remote_avatar else None
        if img:
            data, fname, ctype = img
            avatar_url = upload_avatar(acc, data, fname, ctype)
        if not avatar_url:
            avatar_url = upload_default_avatar(acc)
    try:
        if not put_profile(avatar_url): return False  # 昵称优先：头像失败也必须保存资料。
    except ApiError:
        return False
    check = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
    _g = (check or {}).get("data");
    got = _g if isinstance(_g, dict) else {}
    if got.get("name") != nickname: return False
    with state_lock:
        account_state = state.setdefault("accounts", {}).setdefault(nick, {})
        account_state["profile_name_done"] = True
        account_state["avatar_pending"] = not bool(got.get("avatar"))
    if got.get("avatar"):
        with state_lock: state.setdefault("avatars", {})[persona["nickname"]] = got["avatar"]
    mark_state_dirty()
    log_action(acc, "PROFILE_SETUP", details=f"Name:{nickname}, Avatar:{bool(got.get('avatar'))}")
    return bool(got.get("avatar"))


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


DM_EVENT_BASE_PROBABILITY = {"continue_public_interaction": .20, "share_life": .12,
                             "ask_private_question": .18, "check_in": .05, "reply_received": .90}


def build_dm_session_context(acc: dict, state: dict, viewed_posts: list) -> dict:
    return {"viewed_accounts": {str(post.get("account")) for post in viewed_posts if post.get("account")},
            "interacted_accounts": set(), "recent_events": get_recent_life_context_for_reply(acc, state, max_events=4)}


def generate_dm_event(acc: dict, state: dict, session_ctx: dict) -> dict | None:
    """本地决定本次会话是否有值得私聊的原因；无事件即不发。"""
    events = session_ctx.get("recent_events", [])
    if events and random.random() < .08:
        event = events[-1]
        return {"type": "share_life", "topic": event.get("description", "今天发生的一件事"),
                "mood": event.get("mood", "normal"), "source": "life_event"}
    if session_ctx.get("interacted_accounts") and random.random() < .12:
        return {"type": "continue_public_interaction", "topic": "刚才聊到的话题", "mood": "engaged", "source": "public_interaction"}
    if random.random() < .025:
        return {"type": "check_in", "topic": "想起很久没聊的人", "mood": "neutral", "source": "relationship_memory"}
    return None


def choose_dm_recipient(acc: dict, state: dict, dm_event: dict, session_ctx: dict) -> dict | None:
    relations = state.get("relationships", {}).get(acc["account"], {})
    candidates = []
    for target_acc, relation in relations.items():
        if not target_acc or target_acc == acc["account"]: continue
        affinity, familiarity = float(relation.get("affinity", 0) or 0), float(relation.get("familiarity", 0) or 0)
        score = affinity * .40 + familiarity * .30 + min(int(relation.get("interactions", 0) or 0) / 20, 1) * .10
        if dm_event["type"] == "share_life": score += familiarity * .30
        if dm_event["type"] == "continue_public_interaction" and target_acc in session_ctx.get("interacted_accounts", set()): score += .60
        if dm_event["type"] == "check_in": score += min((time.time() - float(relation.get("last_contact_at", 0) or 0)) / 86400 / 30, 1) * .40
        candidates.append({"account": target_acc, "name": relation.get("name", "对方"), "relation": relation, "score": score})
    if not candidates: return None
    top = sorted(candidates, key=lambda item: item["score"], reverse=True)[:5]
    return random.choices(top, weights=[max(.01, item["score"]) for item in top], k=1)[0]


def calculate_dm_probability(acc: dict, relation: dict, dm_event: dict) -> float:
    affinity, familiarity = float(relation.get("affinity", 0) or 0), float(relation.get("familiarity", 0) or 0)
    probability = DM_EVENT_BASE_PROBABILITY.get(dm_event["type"], .03) * (.50 + affinity * .30 + familiarity * .40)
    personality = str(acc.get("personality") or "")
    if "热情" in personality: probability *= 1.25
    if "话痨" in personality: probability *= 1.30
    if "内向" in personality: probability *= .70
    if "社恐" in personality: probability *= .55
    return max(.01, min(.95, probability))


def should_send_dm(acc: dict, state: dict, target_acc: str, relation: dict, dm_event: dict) -> tuple[bool, str]:
    now = time.time()
    with state_lock:
        account_state = state.setdefault("accounts", {}).setdefault(acc["nickname"], {})
        dm_state = account_state.setdefault("dm_state", {"last_outbound_dm_at": 0, "daily_outbound_count": 0,
                                                           "daily_count_date": "", "recent_dm_events": []})
    today = datetime.now().date().isoformat()
    if dm_state.get("daily_count_date") != today:
        dm_state["daily_count_date"], dm_state["daily_outbound_count"] = today, 0
    if now - float(dm_state.get("last_outbound_dm_at", 0) or 0) < 1800: return False, "global_cooldown"
    if dm_event["type"] != "reply_received" and now - float(relation.get("last_dm_at", 0) or 0) < 21600: return False, "recipient_cooldown"
    if int(dm_state.get("daily_outbound_count", 0) or 0) >= 5: return False, "daily_limit"
    if dm_event["type"] != "reply_received" and float(relation.get("affinity", 0) or 0) < .25 and float(relation.get("familiarity", 0) or 0) < .30:
        return False, "relationship_too_weak"
    return (True, "ok") if random.random() < calculate_dm_probability(acc, relation, dm_event) else (False, "probability")


def record_dm_sent(acc: dict, state: dict, target_acc: str, dm_event: dict) -> None:
    now, today = time.time(), datetime.now().date().isoformat()
    with state_lock:
        dm_state = state.setdefault("accounts", {}).setdefault(acc["nickname"], {}).setdefault("dm_state", {})
        dm_state["last_outbound_dm_at"] = now
        dm_state["daily_count_date"] = today
        dm_state["daily_outbound_count"] = int(dm_state.get("daily_outbound_count", 0) or 0) + 1
        dm_state["recent_dm_events"] = (dm_state.get("recent_dm_events", []) + [{"type": dm_event["type"], "at": now}])[-20:]
        relation = _ensure_relation(state, acc["account"], target_acc, "对方")
        relation.update({"last_dm_at": now, "last_dm_direction": "outbound", "last_dm_event_type": dm_event["type"],
                         "dm_count": int(relation.get("dm_count", 0) or 0) + 1, "last_contact_at": now})
    mark_state_dirty()


def generate_dm_text(persona: dict, target_name: str, history: list, relation: dict, dm_event: dict) -> str:
    lang_req = f"必须严格使用 {persona['prompt_lang']} 语言。"
    history_text = "（暂无历史记录，这是你主动发起的搭讪）"
    if history:
        my_acc = persona.get("account", "");
        lines = []
        for msg in history:
            sender_name = "我" if msg["sender"] == my_acc else target_name
            lines.append(f"{sender_name}: {msg['content']}")
        history_text = "\n".join(lines)
    prompt = (
        f"你正在社交软件上给 {target_name} 发私信。你们的关系：好感度 {float(relation.get('affinity', 0)):.2f}，熟悉度 {float(relation.get('familiarity', 0)):.2f}。\n"
        f"这次私聊原因：{dm_event['type']}；具体事情：{dm_event.get('topic', '')}；当前情绪：{dm_event.get('mood', 'normal')}。\n"
        f"你的性格是：{persona.get('personality', '普通')}，人设：{persona.get('bio', '')}。\n{lang_req}\n"
        f"以下是你们的最近聊天记录：\n{history_text}\n\n"
        f"请根据这件具体事情自然发消息，不要无缘无故暧昧或假装关系比实际亲密。口语化，10~60 字，只输出消息内容。")
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
    r = http_json("GET", "/comments/getComments", params={"postId": str(post_id), "page": 1, "size": 20},
                  token=acc["token"], silent_404=True)
    data = (r or {}).get("data")
    return data if isinstance(data, list) else []


def get_recent_life_context_for_reply(acc: dict, state: dict, max_events: int = 4) -> list:
    with state_lock:
        events = state.get("accounts", {}).get(acc["nickname"], {}).get("recent_life_events", [])
        return list(events[-max_events:]) if isinstance(events, list) else []


def _keyword_scores(text: str, keyword_map: dict) -> dict:
    text = (text or "").lower()
    scores = {}
    for category, keywords in keyword_map.items():
        score = sum(1.5 if len(keyword) >= 4 else 1.0 if len(keyword) >= 2 else .35
                    for keyword in keywords if keyword.lower() in text)
        if score: scores[category] = score
    return scores


def detect_comment_emotion(text: str) -> tuple[str, float]:
    text = (text or "").strip()
    if not text: return "neutral", 0.0
    scores = _keyword_scores(text, COMMENT_EMOTION_KEYWORDS)
    if "?" in text or "？" in text: scores["curious"] = scores.get("curious", 0) + .35
    if "??" in text or "？？" in text: scores["surprised"] = scores.get("surprised", 0) + .50
    if not scores: return "neutral", .20
    emotion = max(scores, key=scores.get)
    return emotion, min(.95, .40 + scores[emotion] * .18)


def detect_question_type(text: str) -> tuple[str | None, float]:
    text = (text or "").strip()
    if not text: return None, 0.0
    scores = _keyword_scores(text, QUESTION_TYPE_KEYWORDS)
    has_question = "?" in text or "？" in text
    if not scores: return ("general", .45) if has_question else (None, 0.0)
    question_type = max(scores, key=scores.get)
    return question_type, min(.95, .50 + scores[question_type] * .15 + (.10 if has_question else 0))


def detect_comment_topics(text: str, max_topics: int = 3) -> list[str]:
    scores = _keyword_scores(text, TOPIC_KEYWORDS)
    return [topic for topic, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:max_topics]]


def analyze_incoming_comment(text: str) -> dict:
    emotion, emotion_confidence = detect_comment_emotion(text)
    question_type, question_confidence = detect_question_type(text)
    return {"emotion": emotion, "emotion_confidence": emotion_confidence, "question_type": question_type,
            "question_confidence": question_confidence, "topics": detect_comment_topics(text), "is_question": question_type is not None}


def find_related_life_events(acc: dict, state: dict, topics: list[str], limit: int = 3) -> list[dict]:
    if not topics: return []
    matches, topic_set = [], set(topics)
    for event in reversed(get_recent_life_context_for_reply(acc, state, max_events=12)):
        if isinstance(event, dict) and topic_set & EVENT_CATEGORY_TOPIC_MAP.get(event.get("category"), set()):
            matches.append(event)
            if len(matches) >= limit: break
    return matches


def choose_reply_intent(acc: dict, state: dict, target_user: str | None, original_post: str,
                        incoming_comment: str, mental_state: str = "normal") -> dict:
    """不调用 LLM：由关系、评论特征和近期事件决定回复意图。"""
    weights = dict(REPLY_INTENT_WEIGHTS)
    analysis = analyze_incoming_comment(incoming_comment)
    emotion, question_type, topics = analysis["emotion"], analysis["question_type"], analysis["topics"]
    related_events = find_related_life_events(acc, state, topics)
    affinity = familiarity = 0.0
    if target_user:
        relation = _ensure_relation(state, acc["account"], target_user, "这位评论者")
        affinity = float(relation.get("affinity", 0) or 0)
        familiarity = float(relation.get("familiarity", 0) or 0)
    if familiarity >= .60:
        weights["tease"] += .18; weights["inside_joke"] += .20; weights["short_reaction"] += .08
    elif familiarity >= .30:
        weights["tease"] += .10; weights["continue_topic"] += .08
    if affinity >= .60:
        weights["own_experience"] += .15; weights["ask_detail"] += .08; weights["disagree"] -= .03
    elif affinity < .10:
        weights["short_reaction"] += .08; weights["own_experience"] -= .04
    comment = (incoming_comment or "").strip().lower()
    emotion_adjustments = {
        "amused": {"tease": .30, "short_reaction": .18, "disagree": -.04}, "agree": {"agree": .30, "continue_topic": .10},
        "disagree": {"clarify": .24, "disagree": .16, "continue_topic": .08}, "surprised": {"short_reaction": .18, "clarify": .12},
        "sympathy": {"agree": .10, "own_experience": .12, "short_reaction": .08}, "annoyed": {"agree": .12, "own_experience": .12, "continue_topic": .08},
        "curious": {"clarify": .20, "continue_topic": .10}, "supportive": {"short_reaction": .15, "continue_topic": .08},
    }
    for reply_type, delta in emotion_adjustments.get(emotion, {}).items(): weights[reply_type] += delta
    if question_type:
        weights["clarify"] += .35; weights["own_experience"] -= .05; weights["disagree"] -= .03
        if question_type in ("result", "reason", "method"): weights["clarify"] += .20
        elif question_type == "opinion": weights["continue_topic"] += .20; weights["disagree"] += .05
        elif question_type == "experience": weights["own_experience"] += .40
        elif question_type in ("price", "location", "time", "identity", "object"): weights["clarify"] += .25
    if len(comment) <= 8:
        weights["short_reaction"] += .18; weights["tease"] += .08; weights["own_experience"] -= .05
    if mental_state == "arrogant": weights["disagree"] += .08; weights["clarify"] += .06
    elif mental_state == "inferior": weights["disagree"] -= .04; weights["agree"] += .06
    elif mental_state == "depressed": weights["short_reaction"] += .12; weights["own_experience"] -= .03
    if related_events: weights["own_experience"] += .25
    else: weights["own_experience"] -= .08
    reply_type = _weighted_choice({key: max(.01, value) for key, value in weights.items()})
    length, instruction = REPLY_INTENT_CONFIG[reply_type]
    return {"type": reply_type, "length": length, "instruction": instruction, "affinity": affinity,
            "familiarity": familiarity, "comment_emotion": emotion, "emotion_confidence": analysis["emotion_confidence"],
            "question_type": question_type, "question_confidence": analysis["question_confidence"],
            "topics": topics, "related_events": related_events}


def maybe_generate_local_short_reply(incoming_comment: str, intent: dict) -> str | None:
    if intent.get("type") != "short_reaction": return None
    comment = (incoming_comment or "").lower()
    if any(token in comment for token in ("哈哈", "hhh", "lol", "😂")): pool = LOCAL_SHORT_REPLIES["amused"]
    elif any(token in comment for token in ("惨", "倒霉", "可怜")): pool = LOCAL_SHORT_REPLIES["sympathy"]
    else: pool = LOCAL_SHORT_REPLIES["agree"]
    return random.choice(pool)


def generate_event_driven_reply(acc: dict, state: dict, original_post: str, incoming_comment: str,
                                target_user: str | None = None, mental_state: str = "normal",
                                max_tokens: int = 120) -> tuple[str | None, dict]:
    intent = choose_reply_intent(acc, state, target_user, original_post, incoming_comment, mental_state)
    local_reply = maybe_generate_local_short_reply(incoming_comment, intent)
    if local_reply: return local_reply, intent
    events = intent.get("related_events", [])
    event_text = "\n".join(f"- {event.get('description', '')}" for event in events if isinstance(event, dict))
    relationship = "陌生的普通评论区用户"
    if intent["familiarity"] >= .70: relationship = "比较熟，可以自然随意地说话"
    elif intent["familiarity"] >= .35: relationship = "已互动过一些次，不算陌生"
    prompt = (
        f"你扮演普通社交网络用户「{acc['nickname']}」（职业：{acc.get('occupation', '普通人')}，性格：{acc.get('personality', '普通')}）。"
        f"必须严格使用 {acc.get('prompt_lang', '简体中文')}。\n关系：{relationship}；好感度 {intent['affinity']:.2f}。\n"
        f"原帖：{original_post}\n对方刚刚评论：{incoming_comment}\n"
        f"本地分析：情绪={intent.get('comment_emotion')}；问题={intent.get('question_type') or '无'}；"
        f"话题={','.join(intent.get('topics') or []) or '未识别'}。\n"
        f"本地已决定回复类型为 {intent['type']}，要求：{intent['instruction']}，长度：{intent['length']}。\n"
        f"你最近真实且与当前话题相关的经历（仅在自然相关时使用，绝不硬塞）：\n{event_text or '无'}\n"
        "直接回复具体评论；若对方提问，优先回答问题。没有相关经历时，不要编造自己也遇到过。"
        "不要复述原帖、总结人生、客服式表达、提及 AI 或输出“回复：”。只输出最终正文。"
    )
    provider_name = acc.get("llm_provider") or get_default_provider_name()
    for _ in range(3):
        reply = _clean_llm_text(llm_generate(prompt, provider_name, max_tokens=max_tokens) or "").strip()
        if len(reply) <= 300 and reply and "```" not in reply and not reply.startswith("{"):
            return reply.strip("\"“”"), intent
    return None, intent


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
                new_replies.append({"post_id": str(pid), "post_text": str(post.get("text") or ""),
                                    "comment_id": cmt_id, "text": cmt_text, "author": cmt_account})
    if not new_replies: return
    personality = acc.get("personality", "普通")
    reply_chance = 0.9 if "热情" in personality or "话痨" in personality else 0.3 if "高冷" in personality or "社恐" in personality else 0.6
    for item in new_replies:
        time.sleep(random.uniform(1.0, 3.0))
        commenter_name = _display_name_for(state, item["author"], "这位评论者")
        reply_driving = calculate_reply_driving_force(item["post_text"], item["text"], acc, state, item["author"])
        reply_fear = calculate_reply_fear_resistance(item["author"], True, acc, state)
        if reply_driving <= reply_fear:
            print(f"🙇 [{nick}] 看到 {commenter_name} 的评论，但因害怕争议选择装死。")
            continue
        adjusted_reply_chance = min(.95, reply_chance + (reply_driving - reply_fear) * .4)
        if random.random() > adjusted_reply_chance:
            print(f"🤐 [{nick}] 想回复 {commenter_name}，犹豫后还是算了。")
            continue
        if dry_run: continue
        mental_state = acc.get("current_mental_state", "normal")
        reply_text, reply_intent = generate_event_driven_reply(
            acc=acc, state=state, original_post=item["post_text"], incoming_comment=item["text"],
            target_user=item["author"], mental_state=mental_state, max_tokens=100)
        if not reply_text: continue
        r = http_json("POST", "/comments/post",
                      {"postsId": item["post_id"], "account": acc["account"], "comments": reply_text,
                       "parentId": item["comment_id"], "replyToAccount": item["author"]}, token=acc["token"])
        if r and r.get("code") == 1:
            with state_lock: state.setdefault("replied_comment_ids", []).append(item["comment_id"])
            stance = "gentle_disagree" if reply_intent["type"] == "disagree" else "supportive" if reply_intent["type"] == "agree" else "neutral"
            record_relationship(state, acc["account"], item["author"], commenter_name, "reply", stance, item["text"])
            log_action(acc, "REPLY", target=item["comment_id"],
                       details=f"Intent:{reply_intent['type']}, Emotion:{reply_intent.get('comment_emotion')}, "
                               f"Question:{reply_intent.get('question_type')}, Topics:{','.join(reply_intent.get('topics') or [])}, "
                               f"RelatedEvents:{len(reply_intent.get('related_events') or [])}, Author:{commenter_name}, "
                               f"Affinity:{reply_intent['affinity']:.2f}, Familiarity:{reply_intent['familiarity']:.2f}, Text:{reply_text[:80]}")
            if reply_intent["type"] in ("disagree", "tease"):
                adjust_fear_of_judgment(acc, state, .02)
            elif reply_intent["type"] in ("agree", "own_experience", "ask_detail"):
                adjust_fear_of_judgment(acc, state, -.04)


def create_post(acc: dict, text: str, dry_run: bool):
    if dry_run: return "dry-post-id"
    r = http_json("POST", "/posts/post", {"account": acc["account"], "text": text,
                                               "language": acc.get("active_post_language", acc.get("lang_code", "unknown"))}, token=acc["token"])
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
def ensure_social_psychology(acc: dict, state: dict) -> None:
    """为旧账号补齐稳定的社交焦虑特质与可持久化的评价恐惧值。"""
    nick = acc["nickname"]
    seed = sum((index + 1) * ord(char) for index, char in enumerate(nick))
    with state_lock:
        account_state = state.setdefault("accounts", {}).setdefault(nick, {})
        anxiety = account_state.get("social_anxiety", acc.get("social_anxiety"))
        if anxiety is None: anxiety = .1 + (seed % 701) / 1000
        fear = account_state.get("fear_of_judgment", acc.get("fear_of_judgment", .2))
        account_state["social_anxiety"] = round(float(anxiety), 3)
        account_state["fear_of_judgment"] = round(min(1.0, max(0.0, float(fear))), 3)
        seen = account_state.get("seen_post_ids", [])
        account_state["seen_post_ids"] = seen[-MAX_SEEN_POST_IDS:] if isinstance(seen, list) else []
    acc["social_anxiety"] = account_state["social_anxiety"]
    acc["fear_of_judgment"] = account_state["fear_of_judgment"]


def update_account_reputation(acc: dict, state: dict):
    nick = acc["nickname"]
    r = http_json("GET", "/posts/getPosts", params={"account": acc["account"]}, token=acc["token"])
    posts = (r or {}).get("data") or []
    total_views = sum(int(p.get("viewCount") or 0) for p in posts if isinstance(p, dict))
    total_likes = sum(int(p.get("likeCount") or 0) for p in posts if isinstance(p, dict))

    # 浏览带来缓慢的基础成长；点赞贡献线性声望；持续高赞会获得爆款加成。
    score = total_views * .01 + total_likes * 2.0 + (total_likes // 10) ** 1.5

    def get_tier(value: float) -> str:
        if value >= 500: return "👑 大V"
        if value >= 100: return "🌟 活跃达人"
        if value >= 20: return "🌱 小萌新"
        return "👻 透明人"

    with state_lock:
        acc_state = state.setdefault("accounts", {}).setdefault(nick, {})
        old_score = float(acc_state.get("reputation_score", 0) or 0)
        acc_state["reputation_score"] = score
        acc_state["total_views"] = total_views
        acc_state["total_likes"] = total_likes
        current_fear = float(acc_state.get("fear_of_judgment", .2) or .2)
        recent_posts = [post for post in posts if isinstance(post, dict)][:3]
        if len(recent_posts) >= 2:
            average_likes = sum(int(post.get("likeCount") or 0) for post in recent_posts) / len(recent_posts)
            if average_likes == 0:
                current_fear = min(1.0, current_fear + .15)
            elif average_likes >= 2:
                current_fear = max(0.0, current_fear - .10)
        acc_state["fear_of_judgment"] = round(current_fear, 3)

    acc["reputation_score"] = score
    acc["fear_of_judgment"] = acc_state["fear_of_judgment"]
    old_tier, current_tier = get_tier(old_score), get_tier(score)
    if current_tier != old_tier and old_score > 1.0:
        print(f"🎉 [{nick}] 账号成长！从 [{old_tier}] 晋升为 [{current_tier}] (当前声望: {score:.1f})")
    elif old_score <= 1.0 and score >= 20:
        print(f"🌱 [{nick}] 账号成长！突破零声望，晋升为 [{current_tier}] (当前声望: {score:.1f})")
    mark_state_dirty()
    return score


def calculate_mental_state(acc: dict, reputation_score: float) -> str:
    income = acc.get("income", "中");
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
    # 稳定地将约 80% 账号划为低发布意愿的潜水者，约 20% 为活跃分享者。
    nick_hash = sum(ord(char) for char in str(acc.get("nickname") or "bot"))
    innate_willingness = .05 if nick_hash % 5 else .40
    base_prob = SESSION_CFG["post"] * innate_willingness
    if score >= 500:
        return min(.25, base_prob + .10), "👑 大V", 9, 400
    elif score >= 100:
        return min(.12, base_prob + .05), "🌟 活跃达人", 6, 300
    elif score >= 20:
        return min(.06, base_prob + .02), "🌱 小萌新", 3, 200
    else:
        return base_prob, "👻 透明人", 2, 150


# ---------------------------------------------------------------------------
# 发帖与用户会话 (V4.0 本地画廊策展版)
# ---------------------------------------------------------------------------
def publish_a_post(acc: dict, state: dict, tier: str, max_imgs: int, llm_tokens: int, mental_state: str = "normal"):
    nick = acc["nickname"]
    if tier == "👑 大V":
        n_select = random.randint(3, min(6, max_imgs))
    elif tier == "🌟 活跃达人":
        n_select = random.randint(1, 3)
    else:
        n_select = random.randint(1, 2)
    if not ENABLE_EXTERNAL_POST_IMAGES: n_select = 0

    if n_select == 0:
        history = fetch_post_history(acc)
        content = gen_text("post", acc, history=history, max_tokens=llm_tokens, mental_state=mental_state)
        if not content: return None
        pid = create_post_with_images(acc, content, [], False)
        if pid: log_action(acc, "POST", target=str(pid), details=f"Text:{content[:100]}")
        return pid

    print(f"📸 [{nick}] 准备发 {n_select} 张图，正在打开本地相册...")
    gallery_files = [f for f in os.listdir(GALLERY_DIR) if os.path.isfile(os.path.join(GALLERY_DIR, f))]

    if len(gallery_files) < n_select:
        print(f"⚠️ [{nick}] 相册库存不足 ({len(gallery_files)}/{n_select})，降级为纯文本发帖")
        history = fetch_post_history(acc)
        content = gen_text("post", acc, history=history, max_tokens=llm_tokens, mental_state=mental_state)
        if not content: return None
        pid = create_post_with_images(acc, content, [], False)
        if pid: log_action(acc, "POST", target=str(pid), details=f"Fallback:Text:{content[:100]}")
        return pid

    # 随机挑选一批图（比如 12 张）让 AI 挑
    batch_size = min(len(gallery_files), max(10, n_select * 3))
    selected_files = random.sample(gallery_files, batch_size)
    gallery_paths = [os.path.join(GALLERY_DIR, f) for f in selected_files]

    # 2. AI 策展 (挑图 + 写文案)
    print(f"🧠 [{nick}] 正在从 {len(gallery_paths)} 张照片中挑选最满意的 {n_select} 张...")
    caption, selected_paths = ai_curate_gallery(acc, gallery_paths, mental_state)

    if not caption or not selected_paths:
        print(f"🤷 [{nick}] AI 策展失败，放弃本次发帖")
        return None

    # 3. 准备上传数据
    imgs_to_upload = []
    for path in selected_paths:
        try:
            with open(path, "rb") as f:
                data = f.read()
            ctype = image_content_type(path)
            imgs_to_upload.append((data, os.path.basename(path), ctype, ""))
        except Exception:
            continue

    # 4. 发帖
    print(f"🚀 [{nick}] 策展完成，发布动态: '{caption[:40]}...'")
    pid = create_post_with_images(acc, caption, imgs_to_upload, False)

    # 🌟 【核心修复】只删除被选中并成功发出的图片！没选中的“废片”留在相册里！
    if pid:
        for p in selected_paths:  # <--- 注意：这里只遍历 selected_paths，而不是 gallery_paths
            try:
                os.remove(p)
            except:
                pass

        leftover_count = len(gallery_paths) - len(selected_paths)
        print(
            f"🗑️ [{nick}] 已清理 {len(selected_paths)} 张已发原图，剩余 {leftover_count} 张废片继续留在相册供下次挑选。")

        log_action(acc, "POST", target=str(pid),
                   details=f"Images:{len(imgs_to_upload)}/{batch_size}, Text:{caption[:100]}")
        if imgs_to_upload:
            with state_lock:
                account_state = state.setdefault("accounts", {}).setdefault(acc["nickname"], {})
                account_state["image_post_count"] = int(account_state.get("image_post_count", 0) or 0) + 1
            mark_state_dirty()

    return pid


def publish_event_driven_post(acc: dict, state: dict, tier: str, max_imgs: int, llm_tokens: int,
                              mental_state: str = "normal", event: dict | None = None):
    """V4.1 发帖路径：事件决定内容，VLM 至多为该内容选图。"""
    nick = acc["nickname"]
    event = event or generate_local_life_event(acc, state)
    intent = build_post_intent(acc, event)
    current_fear = float(acc.get("fear_of_judgment", .2) or .2)
    if current_fear > .6:
        intent["style"] += "，语气小心试探，可用轻微自嘲或表情掩饰不安"
    elif current_fear > .4:
        intent["style"] += "，避免过于绝对的表达，语气稍微不自信"
    print(f"🌍 [{nick}] 生活事件: {event['description']} | mood={event['mood']} | type={intent['post_type']} | fear={current_fear:.2f}")
    content = generate_event_driven_post(acc, state, event, intent, mental_state, llm_tokens)
    if not content:
        print(f"⚠️ [{nick}] 事件动态生成失败")
        return None

    selected_paths = []
    batch_size = 0
    wants_image = False
    if ENABLE_EXTERNAL_POST_IMAGES:
        # 👇 增加 0.1 (10%) 的基础带图概率，让所有类型的帖子都有更高几率配图
        base_image_probability = EVENT_IMAGE_PROBABILITY.get(intent["post_type"], .05)+0.15
        account_state = state.get("accounts", {}).get(acc["nickname"], {})
        past_image_posts = int(account_state.get("image_post_count", 0) or 0)
        if past_image_posts > 0:
            base_image_probability = min(.75, base_image_probability * 4.0 + .25)
        wants_image = random.random() < base_image_probability
    if wants_image and max_imgs > 0:
        gallery_files = [f for f in os.listdir(GALLERY_DIR) if os.path.isfile(os.path.join(GALLERY_DIR, f))]
        if gallery_files:
            image_limit = min(max_imgs, 6 if tier == "👑 大V" else 3 if tier == "🌟 活跃达人" else 2)
            batch_size = min(len(gallery_files), max(10, image_limit * 3))
            candidates = [os.path.join(GALLERY_DIR, name) for name in random.sample(gallery_files, batch_size)]
            print(f"🧠 [{nick}] 正在从 {batch_size} 张相册照片中挑选与事件匹配的图片...")
            selected_paths = curate_images_for_event(acc, candidates, event, content, image_limit)

    images = []
    for path in selected_paths:
        try:
            with open(path, "rb") as f: data = f.read()
            images.append((data, os.path.basename(path), image_content_type(path), ""))
        except OSError: continue
    pid = create_post_with_images(acc, content, images, False)
    if not pid: return None
    remember_life_event(acc, state, event)
    for path in selected_paths:
        try: os.remove(path)
        except OSError: pass
    if images:
        with state_lock:
            account_state = state.setdefault("accounts", {}).setdefault(acc["nickname"], {})
            account_state["image_post_count"] = int(account_state.get("image_post_count", 0) or 0) + 1
        mark_state_dirty()
    log_action(acc, "POST", target=str(pid),
               details=f"Event:{event['category']}/{event['mood']}, Type:{intent['post_type']}, Images:{len(images)}/{batch_size}, Text:{content[:100]}")
    return pid


def simulate_user_session(acc: dict, state: dict, dry_run: bool, skip_profile_setup: bool = False):
    global _active_sessions_count
    nick = acc["nickname"];
    nat = acc.get('nationality', '未知')
    with _active_sessions_lock:
        _active_sessions_count += 1; current_online = _active_sessions_count
    with state_lock:
        total_accounts = len(state.get("accounts", {}))
    log_action(acc, "SESSION_START", details=f"Nat:{nat}, Online:{current_online}/{total_accounts}")
    try:
        if dry_run: return
        with state_lock:
            profile_state = state["accounts"].get(nick, {})
            needs_profile_setup = not profile_state.get("profile_done")
            profile_name_done = bool(profile_state.get("profile_name_done"))
        # 已完成资料的账号也会低频检查头像是否仍存在，避免历史空头像永久遗漏。
        if not needs_profile_setup and random.random() < AVATAR_RETRY_PROBABILITY:
            current_user = http_json("GET", "/user/getUser", params={"account": acc["account"]}, token=acc["token"])
            user_data = (current_user or {}).get("data")
            if isinstance(user_data, dict) and not user_data.get("avatar"):
                with state_lock:
                    profile_state = state["accounts"].setdefault(nick, {})
                    profile_state["profile_done"] = False
                    profile_state["profile_name_done"] = True
                    profile_state["avatar_pending"] = True
                needs_profile_setup, profile_name_done = True, True
                mark_state_dirty()
        if needs_profile_setup:
            # 已保存昵称但暂时缺头像的账号随机重试，未完成前不参与社区活动。
            if profile_name_done and random.random() >= AVATAR_RETRY_PROBABILITY:
                log_action(acc, "PROFILE_PENDING", details="Avatar retry deferred")
                return
            time.sleep(random.uniform(3.0, 15.0));
            throttle_avatar()
            persona = {"nickname": nick, "bio": acc.get("bio", ""), "avatar_desc": acc.get("avatar_desc", ""),
                       "llm_provider": acc.get("llm_provider") or get_default_provider_name()}
            if setup_profile(acc, persona, state, False, try_remote_avatar=not skip_profile_setup):
                interests = ensure_agent_interests(acc, state)
                with state_lock:
                    state["accounts"][nick]["profile_done"] = True;
                    state["accounts"][nick]["avatar_pending"] = False
                    state["accounts"][nick]["bio"] = acc.get("bio", "");
                    state["accounts"][nick]["avatar_desc"] = acc.get("avatar_desc", "")
                    state["accounts"][nick]["personality"] = acc.get("personality", "普通");
                    state["accounts"][nick]["nationality"] = acc.get("nationality", "")
                    state["accounts"][nick]["language"] = acc.get("language", "");
                    state["accounts"][nick]["lang_code"] = acc.get("lang_code", "unknown")
                    state["accounts"][nick]["prompt_lang"] = acc.get("prompt_lang", "简体中文");
                    state["accounts"][nick]["interests"] = interests
                    state["accounts"][nick]["llm_provider"] = acc.get("llm_provider") or get_default_provider_name()
                mark_state_dirty()
            else:
                log_action(acc, "PROFILE_PENDING", details="Name saved; avatar upload pending", level="WARNING")
                return
        ensure_social_psychology(acc, state)
        ensure_language_profile(acc, state)
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
        with state_lock:
            seen_post_ids = list(state["accounts"].get(nick, {}).get("seen_post_ids", []))[-MAX_SEEN_POST_IDS:]
        posts = fetch_latest_posts(acc, limit=20, exclude_ids=seen_post_ids)
        if not posts: return
        with state_lock:
            acc_state = state["accounts"].get(nick, {}); already_following = set(acc_state.get("following", []))
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
        interacted_accounts = set()
        session_id = uuid.uuid4().hex
        for post in browse:
            pid = post.get("id");
            ptext = post.get("text", "");
            pauthor = post.get("account", "")
            if not pid or pauthor == acc["account"]: continue
            author_data = post.get("user") if isinstance(post.get("user"), dict) else {}
            author_name = author_data.get("name") or _display_name_for(state, pauthor, "这位作者")
            interest_score = local_interest_score(acc, state, post, already_following)
            view_probability = max(0.05, min(0.98, 0.12 + interest_score * 0.82 + random.uniform(-0.10, 0.10)))
            if random.random() > view_probability: continue
            if not report_post_view(acc, str(pid)): continue
            if str(pid) not in seen_post_ids:
                seen_post_ids.append(str(pid))
                with state_lock:
                    state["accounts"].setdefault(nick, {})["seen_post_ids"] = seen_post_ids[-MAX_SEEN_POST_IDS:]
                mark_state_dirty()
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
                comment_probability *= 0.4; like_probability *= 1.2
            elif mental_state == "arrogant":
                comment_probability *= 1.8; like_probability *= 0.3
            elif mental_state == "depressed":
                comment_probability *= 0.2; like_probability *= 0.3
            if post.get("isLike") == 0 and random.random() < like_probability:
                if like_post(acc, pid, False):
                    record_relationship(state, acc["account"], pauthor, author_name, "like", "supportive", ptext)
                    log_action(acc, "LIKE", target=str(pid), details=f"Author:{author_name}")
                    interacted_accounts.add(pauthor)
                time.sleep(random.uniform(0.5, 1.5))

            # 🌟 高兴趣直接关注机制（一见钟情）
            if interest_score > 0.85 and pauthor not in already_following and random.random() < 0.30:
                if not dry_run:
                    is_fan = check_is_following(acc["account"], pauthor, acc["token"])
                    if not is_fan:
                        if toggle_follow(acc["account"], pauthor, acc["token"]):
                            already_following.add(pauthor)
                            log_action(acc, "FOLLOW", target=pauthor,
                                       details=f"Reason:HighInterest({interest_score:.2f})")
                else:
                    already_following.add(pauthor)

            reply_driving = calculate_reply_driving_force(ptext, "", acc, state, pauthor)
            reply_fear = calculate_reply_fear_resistance(pauthor, False, acc, state)
            post_language = str(post.get("language") or detect_lang(ptext))
            comment_language = choose_comment_language(acc, post_language)
            if reply_driving > reply_fear:
                adjusted_comment_probability = min(.85, comment_probability + (reply_driving - reply_fear) * .5)
            else:
                adjusted_comment_probability = 0.0
                print(f"🙇 [{nick}] 想评论 {author_name} 的帖子，但害怕说错话，默默划走。"
                      f" (推动:{reply_driving:.2f} < 阻力:{reply_fear:.2f})")
            if comment_language is None:
                adjusted_comment_probability = 0.0
            if random.random() < adjusted_comment_probability:
                stance = choose_interaction_stance(state, acc["account"], pauthor, author_name)
                c = gen_text("comment", {**acc, "prompt_lang": LANGUAGE_PROMPT_NAMES.get(comment_language, acc.get("prompt_lang", "English")),
                                         "target": ptext, "interaction_stance": stance,
                                         "relationship_context": relationship_context(state, acc["account"], pauthor,
                                                                                      author_name)},
                             mental_state=mental_state)
                if not c: continue
                if comment_post(acc, pid, c, pauthor, False):
                    record_relationship(state, acc["account"], pauthor, author_name, "comment", stance, ptext)
                    log_action(acc, "COMMENT", target=str(pid), details=f"Author:{author_name}, Text:{c[:80]}")
                    interacted_accounts.add(pauthor)
                    relation_after = state.get("relationships", {}).get(acc["account"], {}).get(pauthor, {})
                    if float(relation_after.get("familiarity", 0) or 0) > .3:
                        adjust_fear_of_judgment(acc, state, -.03)
                time.sleep(random.uniform(2.0, 4.0))
        # 先在本地生成事件，再让表达冲动与评价恐惧共同决定是否敢发帖。
        event = generate_local_life_event(acc, state)
        driving_force = calculate_driving_force(event, acc)
        current_fear = float(acc.get("fear_of_judgment", .2) or .2)
        anxiety_trait = float(acc.get("social_anxiety", .3) or .3)
        fear_resistance = current_fear * (1.0 + anxiety_trait)
        if mental_state in ("inferior", "depressed"): fear_resistance *= 1.5
        print(f"🧠 [{nick}] 情绪推动力: {driving_force:.2f} | 恐惧阻力: {fear_resistance:.2f}")
        posted = False
        if driving_force > fear_resistance:
            margin = driving_force - fear_resistance
            final_post_probability = min(.80, post_prob + margin * .5)
            if random.random() < final_post_probability:
                print(f"🦁 [{nick}] 鼓起勇气突破恐惧，准备发帖！")
                posted = bool(publish_event_driven_post(acc, state, tier, max_imgs, llm_tokens, mental_state, event))
                if posted: time.sleep(random.uniform(2.0, 5.0))
            else:
                print(f"🤐 [{nick}] 虽有冲动，但还是选择潜水。")
        else:
            print(f"🙇 [{nick}] 恐惧感占据上风，默默划走。")
        if not posted:
            with state_lock:
                account_state = state.setdefault("accounts", {}).setdefault(nick, {})
                account_state["fear_of_judgment"] = min(1.0, current_fear + .02)
                acc["fear_of_judgment"] = account_state["fear_of_judgment"]
            mark_state_dirty()
        if posted or random.random() < .4:
            check_and_reply_interactions(acc, state, False)
        my_relations = state.get("relationships", {}).get(acc["account"], {})
        followed_count = 0
        for target_acc, relation in my_relations.items():
            if not target_acc or target_acc == acc["account"]: continue
            affinity = float(relation.get("affinity", 0));
            familiarity = float(relation.get("familiarity", 0))
            # 🛠️ 降低关注阈值，让关系更容易突破
            should_follow = (familiarity >= 0.25 and affinity >= 0.20) or (affinity >= 0.45)
            if should_follow and target_acc not in already_following:
                if not dry_run:
                    is_fan = check_is_following(acc["account"], target_acc, acc["token"])
                    if not is_fan:
                        if toggle_follow(acc["account"], target_acc, acc["token"]):
                            already_following.add(target_acc);
                            followed_count += 1
                            log_action(acc, "FOLLOW", target=target_acc, details=f"Reason:Affinity({affinity:.2f})")
                    else:
                        already_following.add(target_acc)
                else:
                    already_following.add(target_acc)
        with state_lock:
            state["accounts"].setdefault(nick, {})["following"] = list(already_following)
        mark_state_dirty()

        # Event-driven DM: 每个会话最多选择一位收件人并发送一条主动私信。
        session_ctx = build_dm_session_context(acc, state, browse)
        session_ctx["interacted_accounts"] = interacted_accounts
        dm_event = generate_dm_event(acc, state, session_ctx)
        if dm_event:
            recipient = choose_dm_recipient(acc, state, dm_event, session_ctx)
            if recipient:
                target_acc, target_name, relation = recipient["account"], recipient["name"], recipient["relation"]
                allowed, reason = should_send_dm(acc, state, target_acc, relation, dm_event)
                if allowed and not dry_run:
                    history = fetch_dm_history(acc["account"], target_acc, acc["token"], limit=5)
                    dm_text = generate_dm_text(acc, target_name, history, relation, dm_event)
                    if dm_text and send_dm(acc["account"], target_acc, dm_text, acc["token"]):
                        record_dm_sent(acc, state, target_acc, dm_event)
                        record_relationship(state, acc["account"], target_acc, target_name, "dm_sent", "neutral", dm_event.get("topic", ""))
                        log_action(acc, "DM", target=target_acc,
                                   details=f"Recipient:{target_name}, Event:{dm_event['type']}, Source:{dm_event['source']}")
                elif not allowed:
                    log_action(acc, "DM_SKIPPED", target=target_acc, details=f"Event:{dm_event['type']}, Reason:{reason}")
    finally:
        with _active_sessions_lock:
            _active_sessions_count -= 1; current_online = _active_sessions_count
        log_action(acc, "SESSION_END", details=f"OnlineLeft:{current_online}")


# ---------------------------------------------------------------------------
# 🌟 分层持续调度系统 (动态贪心版)
# ---------------------------------------------------------------------------
def get_scheduling_batch(state: dict, concurrent_limit: int) -> list:
    accounts = state.get("accounts", {});
    now = time.time();
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
        random.shuffle(all_available);
        batch = all_available[:concurrent_limit]
    else:
        batch = [];
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
                acc["personality"] = cached.get("personality", "普通");
                acc["nationality"] = cached.get("nationality", "")
                acc["language"] = cached.get("language", "");
                acc["lang_code"] = cached.get("lang_code", "unknown")
                acc["prompt_lang"] = cached.get("prompt_lang", acc.get("language") or "简体中文")
                acc["interests"] = cached.get("interests", []);
                acc["occupation"] = cached.get("occupation", "普通职员")
                acc["income"] = cached.get("income", "中");
                acc["country_code"] = cached.get("country_code", "")
                acc["education"] = cached.get("education", "high_school")
                acc["language_profile"] = cached.get("language_profile", {})
                acc["llm_provider"] = cached.get("llm_provider") or get_default_provider_name()
                ensure_language_profile(acc, state)
                ensure_agent_interests(acc, state);
                mark_account_ready(nick)
                print(f"✅ [工厂] [{idx}/{len(reuse)}] {nick} 已登录，可立即调度")
            else:
                print(f"⚠️ [工厂] [{idx}/{len(reuse)}] {nick} 登录失败，本次启动不调度", file=sys.stderr)
            if factory_stop_event.wait(args.interval): break
        print("✅ [工厂] 老账号登录遍历完成，进入自然增长循环")
        while not factory_stop_event.is_set():
            active_count = ready_account_count()
            if active_count >= args.agents: factory_stop_event.wait(60); continue
            used_pool = list(state.get("accounts", {}).keys()) + list(state.get("personas", {}).keys())
            persona = gen_persona(0, used_pool, state)
            if not persona: factory_stop_event.wait(60); continue
            if persona["nickname"] in state.get("accounts", {}): factory_stop_event.wait(1); continue
            state.setdefault("personas", {})[persona["nickname"]] = persona["bio"]
            acc = login_agent(state, persona["nickname"], args.dry_run, persona)
            if not acc: factory_stop_event.wait(5); continue
            acc["bio"] = persona["bio"]
            acc.update({key: persona.get(key) for key in
                        ("personality", "nationality", "country_code", "language", "lang_code", "prompt_lang", "interests",
                         "occupation", "income", "education", "language_profile")})
            acc["llm_provider"] = persona.get("llm_provider") or get_default_provider_name()
            ensure_language_profile(acc, state)
            ensure_agent_interests(acc, state);
            mark_account_ready(persona["nickname"])
            print(f"✨ [工厂] 新账号 {persona['nickname']} 已登录，可立即调度")
            factory_stop_event.wait(random.uniform(20, 60))
    except Exception as e:
        print(f"🚨 [工厂] 致命错误导致工厂线程崩溃: {e}", file=sys.stderr)
        traceback.print_exc()


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="AI 社区模拟机器人（V4.0-RealLife 真实生活照版）")
    ap.add_argument("--agents", type=int, default=10000, help="目标账号池总数")
    ap.add_argument("--concurrent", type=int, default=40, help="同时在线人数")
    ap.add_argument("--like-chance", type=float, default=0.40)
    ap.add_argument("--comment-chance", type=float, default=0.15)
    ap.add_argument("--post-chance", type=float, default=0.10)
    ap.add_argument("--no-avatar", action="store_true", help="跳过网络头像抓取，仍设置昵称并上传默认头像")
    ap.add_argument("--interval", type=float, default=0.5, help="老号登录间隔")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划")
    ap.add_argument("--rotate-tokens", action="store_true", help="启动前重新签发所有账号令牌")
    ap.add_argument("--rotate-tokens-only", action="store_true", help="只轮换账号令牌，完成后退出")
    args = ap.parse_args()
    SESSION_CFG.update({"like": args.like_chance, "comment": args.comment_chance, "post": args.post_chance})
    state = load_state()
    clean_and_convert_gallery()
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

    # 🌟 启动后台画廊进货线程
    gallery_thread = threading.Thread(target=background_gallery_worker, daemon=True)
    gallery_thread.start()

    try:
        round_count = 0
        while True:
            round_count += 1
            _ready_accounts_changed.clear()
            batch = get_scheduling_batch(state, args.concurrent)
            if not batch:
                _ready_accounts_changed.wait(10)
                continue
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrent) as ex:
                futures = {ex.submit(simulate_user_session, acc, state, args.dry_run, args.no_avatar): acc for acc in
                           batch}
                concurrent.futures.wait(futures.keys())
                error_accounts = []
                for future, acc in futures.items():
                    nick = acc.get("nickname", "Unknown");
                    exc = future.exception()
                    if exc is not None:
                        error_accounts.append(nick);
                        error_msg = f"{type(exc).__name__}: {str(exc)}"
                        log_action(agent=acc, action="SESSION_ERROR", target=nick, details=error_msg, level="ERROR")
                        with state_lock:
                            acc_state = state["accounts"].get(nick, {})
                            acc_state["error_count"] = acc_state.get("error_count", 0) + 1
                            if acc_state["error_count"] >= 3: acc_state["status"] = "error_suspended"
                if error_accounts: mark_state_dirty()
            flush_state(state, force=False)
            active_count = ready_account_count()
            if active_count < args.agents:
                time.sleep(random.uniform(2.0, 5.0))
            else:
                time.sleep(random.uniform(30.0, 60.0))
    except KeyboardInterrupt:
        print("\n\n🛑 [系统] 收到停止指令，正在通知工厂停工并保存状态...")
        factory_stop_event.set()
        flush_state(state, force=True)
        print("👋 赛博社区已停止运转。")


if __name__ == "__main__":
    main()
