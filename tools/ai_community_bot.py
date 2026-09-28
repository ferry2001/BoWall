#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 社区模拟机器人（低成本版）

思路：
  1. 用极便宜的 API（DeepSeek / 智谱 GLM-4-Flash(免费) / 通义 / Kimi / 本地 Ollama）
     批量生成"人设 + 发帖 + 评论"文本；
  2. 不配置任何 key 时自动退化为本地模板，仍然可以把社区灌满数据（0 成本）；
  3. Codex / GPT 只用来做编排、抽查、调 prompt，不再逐条消耗额度。

依赖：仅 Python 标准库，无需 pip install。

用法示例：
  # 先看计划，不发任何请求
  python tools/ai_community_bot.py --dry-run --agents 5 --posts-per-agent 2

  # 正式灌入本地后端（0 成本模板模式）
  export BOWALL_BASE=http://localhost:8080
  python tools/ai_community_bot.py --agents 5 --posts-per-agent 2 --comments-per-post 3

  # 接便宜 LLM 让内容更真实（OpenAI 兼容协议，换服务商只改环境变量）
  export BOT_LLM_URL=https://api.deepseek.com/chat/completions
  export BOT_LLM_KEY=sk-xxxx
  export BOT_LLM_MODEL=deepseek-chat
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get("BOWALL_BASE", "http://localhost:8080")

# ---------------------------------------------------------------------------
# LLM 接入层：OpenAI 兼容 chat/completions 协议
#   DeepSeek: https://api.deepseek.com/chat/completions  (deepseek-chat, ~1元/百万token)
#   智谱GLM-4-Flash: https://open.bigmodel.cn/api/paas/v4/chat/completions (免费)
#   通义:     https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
#   Ollama:   http://localhost:11434/v1/chat/completions (本地, 完全免费)
# ---------------------------------------------------------------------------
LLM_URL = os.environ.get("BOT_LLM_URL", "https://api.deepseek.com/chat/completions")
LLM_KEY = os.environ.get("BOT_LLM_KEY", "")
LLM_MODEL = os.environ.get("BOT_LLM_MODEL", "deepseek-chat")


def llm_generate(prompt: str, max_retry: int = 2):
    """调用便宜 LLM 生成一段文本；未配置 key 或失败时返回 None（由模板兜底）。"""
    if not LLM_KEY:
        return None
    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 1.1,          # 社区灌水场景，温度拉高更"像人"
        "max_tokens": 200,
    }).encode("utf-8")
    for i in range(max_retry):
        try:
            req = urllib.request.Request(LLM_URL, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {LLM_KEY}",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001
            print(f"  [llm] 第{i + 1}次调用失败: {e}", file=sys.stderr)
            time.sleep(1 + i)
    return None


# ---------------------------------------------------------------------------
# 零成本兜底模板（完全不外部模型也能跑通全流程）
# ---------------------------------------------------------------------------
NAMES = ["夜航星", "程序员小李", "咖啡因过量", "山间竹雨", "深潜者Neo", "橘子汽水",
         "凌晨四点的Bug", "旅行青蛙", "像素猫", "半糖去冰", "键盘诗人", "慢速光年"]

BIOS = ["后端工程师，爱喝咖啡", "自由职业旅行者", "大三学生，准备考研",
        "产品经理，业余跑者", "设计师，养了两只猫", "数据分析师，健身爱好者"]

POST_TEMPLATES = [
    "今天把困扰三天的并发 Bug 修了，原来是连接池没释放。记录一下，也提醒别踩坑。",
    "周末爬了一次后山，云海真的值回票价。照片在评论区补。",
    "读完《置身事内》，对地方政府激励机制有了全新理解，推荐。",
    "自己搭了个 NAS，跑了套媒体服务器，全家终于不用抢视频会员了。",
    "请教一下大家：Spring Boot 里虚拟线程和传统线程池，你们线上用的哪种？",
    "早餐摊的豆浆从 2 块涨到 3 块了，通胀原来藏在生活细节里。",
    "重写了博客的评论系统，接了个便宜大碗的国产模型做审核，效果意外的好。",
    "跑步打卡第 30 天，配速没进步，但膝盖不疼了，这就是胜利。",
]

COMMENT_TEMPLATES = [
    "同款经历！我也是栽在连接池上。",
    "写得真好，收藏了。",
    "顶一个，期待后续更新。",
    "有链接吗？想看看详细版本。",
    "哈哈哈太真实了。",
    "学习了，正好在研究这个。",
    "羡慕，我们这边看不到云海 :(",
    "支持一下，欢迎多分享。",
]


def gen_text(kind: str, persona: dict) -> str:
    """优先走便宜 LLM，失败/未配置则走本地模板。"""
    if LLM_KEY:
        if kind == "post":
            p = (f"你扮演社区用户「{persona['nickname']}」，人设：{persona['bio']}。"
                 f"以他/她的口吻发一条中文社区动态，50~120字，口语化，不要话题标签，只输出正文。")
        else:
            p = (f"你是社区用户「{persona['nickname']}」。请针对下面这条帖子写一条 10~40 字的"
                 f"中文评论，自然一点，可以带点个人经验：\n{persona.get('target', '')}\n只输出评论。")
        out = llm_generate(p)
        if out:
            return out.replace("\n", "")[:280]
    pool = POST_TEMPLATES if kind == "post" else COMMENT_TEMPLATES
    return random.choice(pool)


# ---------------------------------------------------------------------------
# BoWall HTTP 层
# ---------------------------------------------------------------------------
def http_json(method: str, path: str, body=None, token=None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        # 若后端 JwtAuthInterceptor 使用其它头名（如 token），在此处一并调整
        headers["Authorization"] = f"Bearer {token}"
        headers["token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  [http] {method} {path} -> {e.code}: "
              f"{e.read().decode('utf-8', 'ignore')[:200]}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  [http] {method} {path} -> {e}", file=sys.stderr)
        return None


STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_state.json")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"accounts": {}}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def login_agent(state: dict, nickname: str, dry_run: bool):
    """登录（手机号不存在时后端自动注册）。randomNum==code 即可通过验证码校验。"""
    account = state["accounts"].get(nickname)
    if account and account.get("token"):
        return account
    phone = "199" + "".join(random.choices("0123456789", k=8))
    code = "".join(random.choices("0123456789", k=6))
    if dry_run:
        print(f"  [dry] POST /user/login  phone={phone}")
        return {"phone": phone, "account": "DRY-" + uuid.uuid4().hex[:8],
                "token": "dry-token", "nickname": nickname}
    r = http_json("POST", "/user/login", {"phone": phone, "code": code, "randomNum": code})
    data = (r or {}).get("data") or {}
    token = data.get("token")
    user = data.get("user") or {}
    if not token:
        print(f"  [login] 失败，检查后端是否启动/接口鉴权: {r}", file=sys.stderr)
        return None
    acc = {"phone": phone, "account": user.get("account"), "token": token, "nickname": nickname}
    state["accounts"][nickname] = acc
    # 完善昵称/简介
    http_json("PUT", "/user", {"account": acc["account"], "name": nickname}, token=token)
    return acc


def main() -> None:
    ap = argparse.ArgumentParser(description="低成本 AI 社区模拟机器人")
    ap.add_argument("--agents", type=int, default=3, help="模拟用户数")
    ap.add_argument("--posts-per-agent", type=int, default=1, help="每个用户发帖数")
    ap.add_argument("--comments-per-post", type=int, default=2, help="每条帖子评论数")
    ap.add_argument("--interval", type=float, default=0.5, help="请求间隔秒数，防限流")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    args = ap.parse_args()

    state = load_state()
    nicknames = random.sample(NAMES, min(args.agents, len(NAMES)))
    personas = [{"nickname": n, "bio": random.choice(BIOS)} for n in nicknames]

    tokens = {}
    for p in personas:
        acc = login_agent(state, p["nickname"], args.dry_run)
        if acc:
            tokens[p["nickname"]] = acc
        time.sleep(args.interval)

    posted = []
    for p in personas:
        acc = tokens.get(p["nickname"])
        if not acc:
            continue
        for _ in range(args.posts_per_agent):
            content = gen_text("post", p)
            if args.dry_run:
                print(f"[dry] {p['nickname']} 发帖: {content[:40]}...")
                posted.append((acc, content))
                continue
            r = http_json("POST", "/posts/post",
                          {"account": acc["account"], "content": content}, token=acc["token"])
            print(f"[post] {p['nickname']}: {'OK' if r else 'FAIL'} - {content[:30]}")
            if r:
                posted.append((acc, content))
            time.sleep(args.interval)

    commenters = list(tokens.values())
    if args.comments_per_post > 0 and commenters:
        for _, content in posted:
            commenter = random.choice(commenters)
            for _ in range(args.comments_per_post):
                c = gen_text("comment", {**commenter, "target": content})
                if args.dry_run:
                    print(f"[dry] {commenter['nickname']} 评论: {c[:30]}...")
                    continue
                # 评论接口为 POST /comments/post，postId 需按实际帖子 ID 补充
                r = http_json("POST", "/comments/post",
                              {"account": commenter["account"], "content": c, "postId": None},
                              token=commenter["token"])
                print(f"[comment] {commenter['nickname']}: {'OK' if r else 'FAIL'} - {c[:20]}")
                time.sleep(args.interval)

    save_state(state)
    print("完成。账号信息缓存在 tools/bot_state.json，下次运行不会重复注册。")


if __name__ == "__main__":
    main()
