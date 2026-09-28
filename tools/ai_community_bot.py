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
class ApiError(Exception):
    """后端返回 code != 1（R.error）时抛出。"""


def http_json(method: str, path: str, body=None, token=None, params=None, raise_on_error=False):
    """调用 BoWall 后端。鉴权：JwtAuthInterceptor 读取 Authorization: Bearer <token>。
    R 结构：code==1 成功；code==0 失败（msg 为错误信息）。"""
    url = BASE + path
    if params:
        from urllib.parse import urlencode
        url += ("&" if "?" in url else "?") + urlencode(params)
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
        print(f"  [api] {method} {path} -> code={r.get('code')} msg={msg}", file=sys.stderr)
    return r


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
    save_state(state)
    # 完善昵称（后端 PUT /user 校验 currentAccount == user.account）
    http_json("PUT", "/user", {"account": acc["account"], "name": nickname}, token=token)
    return acc


# ---------------------------------------------------------------------------
# 社交动作：发帖 / 评论 / 点赞 / 关注（接口参数均已对照后端 Controller 源码）
# ---------------------------------------------------------------------------
def create_post(acc: dict, text: str, dry_run: bool):
    """POST /posts/post  body={"account","text"} -> data 即新帖子 postId"""
    if dry_run:
        print(f"[dry] {acc['nickname']} 发帖: {text[:50]}")
        return "dry-post-id"
    r = http_json("POST", "/posts/post", {"account": acc["account"], "text": text},
                  token=acc["token"])
    if r and r.get("code") == 1:
        pid = r.get("data")  # 后端返回 UUID 字符串
        print(f"[post] {acc['nickname']}: OK id={pid} - {text[:30]}")
        return pid
    print(f"[post] {acc['nickname']}: FAIL - {text[:30]}")
    return None


def comment_post(acc: dict, post_id: str, text: str, target_account: str, dry_run: bool):
    """POST /comments/post  body={"postsId","account","comments","parentId","replyToAccount"}"""
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
    """POST /like  body={"account","postId"}（重复调用会取消点赞，所以只点一次）"""
    if dry_run:
        print(f"[dry] {acc['nickname']} 点赞 {post_id[:8]}")
        return True
    r = http_json("POST", "/like", {"account": acc["account"], "postId": post_id},
                  token=acc["token"])
    ok = bool(r) and r.get("code") == 1
    print(f"[like] {acc['nickname']}: {'OK' if ok else 'FAIL'} {post_id[:8]}")
    return ok


def follow(from_acc: dict, to_acc: dict, dry_run: bool):
    """POST /user/add  body={"account":被关注人,"fansAccount":操作者}，必须用操作者的 token"""
    if dry_run:
        print(f"[dry] {from_acc['nickname']} 关注 {to_acc['nickname']}")
        return True
    r = http_json("POST", "/user/add",
                  {"account": to_acc["account"], "fansAccount": from_acc["account"]},
                  token=from_acc["token"])
    ok = bool(r) and r.get("code") == 1
    print(f"[follow] {from_acc['nickname']} -> {to_acc['nickname']}: {'OK' if ok else 'FAIL'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description="低成本 AI 社区模拟机器人")
    ap.add_argument("--agents", type=int, default=3, help="模拟用户数")
    ap.add_argument("--posts-per-agent", type=int, default=1, help="每个用户发帖数")
    ap.add_argument("--comments-per-post", type=int, default=2, help="每条帖子评论数")
    ap.add_argument("--likes-per-post", type=int, default=2, help="每条帖子点赞数")
    ap.add_argument("--follow", action="store_true", help="让机器人之间互相关注")
    ap.add_argument("--interval", type=float, default=0.5, help="请求间隔秒数，防限流")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    args = ap.parse_args()

    if LLM_KEY:
        print(f"[llm] 使用模型 {LLM_MODEL} @ {LLM_URL}")
    else:
        print("[llm] 未配置 BOT_LLM_KEY，使用本地模板（0 成本）。"
              "接 DeepSeek: export BOT_LLM_KEY=sk-xxx")

    state = load_state()
    nicknames = random.sample(NAMES, min(args.agents, len(NAMES)))
    personas = [{"nickname": n, "bio": random.choice(BIOS)} for n in nicknames]

    tokens = {}
    for p in personas:
        acc = login_agent(state, p["nickname"], args.dry_run)
        if acc:
            tokens[p["nickname"]] = acc
        time.sleep(args.interval)

    # 互相关注，形成社交关系网
    if args.follow and len(tokens) >= 2:
        accs = list(tokens.values())
        for a in accs:
            for b in accs:
                if a is not b:
                    follow(a, b, args.dry_run)
                    time.sleep(args.interval)

    # 发帖：记录 (postId, 作者account, 正文)，供后续互动
    posted = []
    for p in personas:
        acc = tokens.get(p["nickname"])
        if not acc:
            continue
        for _ in range(args.posts_per_agent):
            content = gen_text("post", p)
            pid = create_post(acc, content, args.dry_run)
            if pid:
                posted.append({"postId": pid, "account": acc["account"],
                               "text": content, "author": acc})
            time.sleep(args.interval)

    # 互动：其他账号对帖子点赞 + 评论
    others = [a for a in tokens.values()]
    for post in posted:
        pool = [a for a in others if a["account"] != post["account"]] or others
        # 点赞（每人每帖只点一次，避免 toggle 取消）
        for liker in random.sample(pool, min(args.likes_per_post, len(pool))):
            like_post(liker, post["postId"], args.dry_run)
            time.sleep(args.interval)
        # 评论
        for _ in range(args.comments_per_post):
            commenter = random.choice(pool)
            text = gen_text("comment", {**commenter, "target": post["text"]})
            comment_post(commenter, post["postId"], text, post["account"], args.dry_run)
            time.sleep(args.interval)

    save_state(state)
    print(f"完成：{len(tokens)} 个账号，{len(posted)} 条帖子。"
          f"账号缓存在 tools/bot_state.json，下次运行不会重复注册。")


if __name__ == "__main__":
    main()
