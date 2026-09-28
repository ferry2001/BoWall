#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 社区模拟机器人（低成本版）

思路：
  1. 所有内容（人设、昵称、简介、帖子、评论）均由 LLM 实时生成，无本地兜底模板；
     默认接 DeepSeek，也可换成任意 OpenAI 兼容服务（智谱 / 通义 / Kimi / 本地 Ollama）。
  2. 未配置 BOT_LLM_KEY 时脚本直接报错退出，不会静默灌入假数据。
  3. Codex / GPT 只用来做编排、抽查、调 prompt，不再逐条消耗额度。

依赖：仅 Python 标准库，无需 pip install。

用法示例：
  # 必须配置 LLM key（DeepSeek 为例）
  export BOT_LLM_KEY=sk-xxxx                          # 必填
  export BOWALL_BASE=http://localhost:8080
  python tools/ai_community_bot.py --agents 5 --posts-per-agent 2 --comments-per-post 3

  # 注册时 AI 自动编网名 + 从网络抓图上传头像（默认开启；--no-avatar 可跳过头像）

  # 先看计划，不发后端请求（仍会调用 LLM 生成人设）
  python tools/ai_community_bot.py --dry-run --agents 3

  # 换服务商只改环境变量（OpenAI 兼容协议）
  export BOT_LLM_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions
  export BOT_LLM_MODEL=glm-4-flash
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid

BASE = os.environ.get("BOWALL_BASE", "http://localhost:8080")
UA = {"User-Agent": "Mozilla/5.0 (compatible; AiCommunityBot/1.0)"}


def http_download(url: str, timeout: int = 20) -> bytes:
    """下载任意 URL 的二进制内容（用于抓取网络头像）。"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_multipart(method: str, path: str, fields: dict, file_field: str,
                   filename: str, file_bytes: bytes, content_type: str, token=None):
    """multipart/form-data 上传，对应后端 @RequestParam MultipartFile 接口。
    fields: 普通表单字段；file_field: 文件字段名。"""
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


def llm_generate(prompt: str, max_retry: int = 3):
    """调用 LLM 生成一段文本；重试后仍失败则直接退出（无模板兜底，避免灌入假数据）。"""
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
    sys.exit(f"[致命] LLM 调用连续失败，已中止（无兜底模板，不灌入假数据）。")


# ---------------------------------------------------------------------------
# 人设 / 帖子 / 评论：全部由 LLM 实时生成（无本地兜底模板）
# ---------------------------------------------------------------------------
def gen_persona(idx: int) -> dict:
    """让 LLM 生成一个拟真人设：昵称 + 简介 + 头像描述。
    输出 JSON: {"nickname":..., "bio":..., "avatar_desc":...}"""
    p = (f"请为一个中文社交社区设计第{idx}个虚拟用户人设，要求像真实普通人："
         f"一个 2~6 字的中文昵称（不要含'用户''测试'等字样），一句 10~20 字的个人简介"
         f"（职业/爱好风格），以及一个与 Ta 气质匹配的头像图片英文描述"
         f"（如 'smiling asian college girl with glasses, casual style'，用于在网络上搜索配图）。"
         f"只输出 JSON：{{\"nickname\":\"...\",\"bio\":\"...\",\"avatar_desc\":\"...\"}}")
    raw = llm_generate(p) or ""
    raw = raw.strip().strip("`").removeprefix("json").strip()
    try:
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        nick = str(d["nickname"]).strip()
        bio = str(d["bio"]).strip()
        avatar_desc = str(d.get("avatar_desc", "")).strip()
        if nick and bio:
            return {"nickname": nick[:20], "bio": bio[:50], "avatar_desc": avatar_desc[:120]}
    except Exception:  # noqa: BLE001
        pass
    sys.exit(f"[致命] 人设生成失败或格式不对（无兜底模板）: {raw[:100]}")


# ---------------------------------------------------------------------------
# 网络头像：从公开免费头像源随机抓取一张真实图片并上传为账号头像
#   - 使用纯图片直链服务（dicebear 生成风 / this-person-does-not-exist 真人风），
#     避免 HTML 页面导致上传非图片文件被后端拒绝。
#   - 下载失败时跳过该账号头像，不影响注册发帖主流程。
# ---------------------------------------------------------------------------
AVATAR_SOURCES = [
    # dicebear：按 seed 生成的卡通头像，稳定、支持 png（路径格式 style/png/seed-xxx.png）
    lambda seed, desc: (
        "https://api.dicebear.com/9.x/lorelei/png/"
        f"seed-{seed}.png?background=c7e3ee&radius=50"),
    lambda seed, desc: (
        "https://api.dicebear.com/9.x/avataaars/png/"
        f"seed-{seed}.png?radius=50"),
    lambda seed, desc: (
        "https://api.dicebear.com/9.x/pixel-art/png/"
        f"seed-{seed}.png?radius=50"),
    # 真人风头像（存在可用性波动，失败自动换下一个源）
    lambda seed, desc: (
        "https://this-person-does-not-exist.com/api?"
        f"gender={random.choice(['f', 'm'])}&age=18-40&_={seed}"),
]


def fetch_avatar(nickname: str, avatar_desc: str) -> tuple | None:
    """尝试多个来源抓取一张头像图片，返回 (bytes, filename, content_type)；全部失败返回 None。"""
    for make_url in AVATAR_SOURCES:
        seed = uuid.uuid4().hex[:12]
        url = make_url(seed, avatar_desc)
        try:
            data = http_download(url)
        except Exception as e:  # noqa: BLE001
            print(f"  [avatar] {nickname}: 下载失败({url[:60]}...) {e}", file=sys.stderr)
            continue
        # 校验魔数，确保拿到的是真图片而不是 HTML 错误页
        if data[:3] == b"\xff\xd8\xff":
            return data, f"{seed}.jpg", "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return data, f"{seed}.png", "image/png"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return data, f"{seed}.gif", "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return data, f"{seed}.webp", "image/webp"
        print(f"  [avatar] {nickname}: 返回内容不是图片({url[:60]}...)，换下一源", file=sys.stderr)
    print(f"  [avatar] {nickname}: 所有头像源均失败，跳过头像", file=sys.stderr)
    return None


def gen_text(kind: str, persona: dict) -> str:
    """生成帖子正文或评论内容；LLM 失败会直接退出，不存在模板回退。"""
    if kind == "post":
        p = (f"你扮演社区用户「{persona['nickname']}」，人设：{persona['bio']}。"
             f"以他/她的口吻发一条中文社区动态，50~120字，口语化，不要话题标签，只输出正文。")
    else:
        p = (f"你是社区用户「{persona['nickname']}」。请针对下面这条帖子写一条 10~40 字的"
             f"中文评论，自然一点，可以带点个人经验：\n{persona.get('target', '')}\n只输出评论。")
    out = llm_generate(p)
    return out.replace("\n", "")[:280]


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
    return acc


def setup_profile(acc: dict, persona: dict, state: dict, dry_run: bool) -> None:
    """注册后完善资料：昵称/签名用 LLM 人设；头像优先复用已上传的 avatar URL，
    否则从网络抓取一张图片，multipart 上传到 POST /user/avatar。
    注意：后端 PUT /user 是全字段更新（name/sign/phone/avatar），
    因此必须先 GET /user/getUser 取回完整记录再合并提交，避免把 phone/avatar 洗成 null。"""
    if dry_run:
        print(f"[dry] {acc['nickname']}: GET /user/getUser -> PUT /user(name,sign) -> "
              f"POST /user/avatar(网络抓图上传)")
        return
    # 1. 取回当前完整用户记录
    r = http_json("GET", "/user/getUser", params={"account": acc["account"]},
                  token=acc["token"])
    user = (r or {}).get("data") or {}
    if not user.get("account"):
        print(f"  [profile] {acc['nickname']}: 获取用户失败，跳过资料设置", file=sys.stderr)
        return
    # 2. 合并人设字段后整体更新（全字段 update）
    payload = {
        "account": user["account"],
        "name": persona["nickname"],
        "sign": persona["bio"],
        "phone": user.get("phone"),
        "address": user.get("address"),
        "status": user.get("status"),
        "avatar": user.get("avatar"),   # 先保留原值
        "password": user.get("password"),
    }
    # 3. 头像：已有则复用（缓存账号不重复下载）；没有则从网络找图并上传
    if not payload["avatar"]:
        cached_avatar = state.setdefault("avatars", {}).get(persona["nickname"])
        if cached_avatar:
            payload["avatar"] = cached_avatar
        else:
            img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""))
            if img:
                data, fname, ctype = img
                up = http_multipart("POST", "/user/avatar",
                                   fields={"account": acc["account"]},
                                   file_field="avatar", filename=fname,
                                   file_bytes=data, content_type=ctype,
                                   token=acc["token"])
                new_avatar = ((up or {}).get("data") or {}).get("avatar")
                if new_avatar:
                    payload["avatar"] = new_avatar
                    state["avatars"][persona["nickname"]] = new_avatar
                    print(f"[avatar] {acc['nickname']}: 上传成功 {new_avatar}")
                else:
                    print(f"[avatar] {acc['nickname']}: 上传失败，继续无头像注册", file=sys.stderr)
    http_json("PUT", "/user", payload, token=acc["token"])


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
    ap.add_argument("--no-avatar", action="store_true", help="跳过网络头像抓取与上传")
    ap.add_argument("--interval", type=float, default=0.5, help="请求间隔秒数，防限流")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不发请求")
    args = ap.parse_args()

    if not LLM_KEY:
        sys.exit("[致命] 必须设置 BOT_LLM_KEY（脚本已移除零成本兜底模板，"
                 "所有内容只由 LLM 生成）。例：export BOT_LLM_KEY=sk-xxx")
    print(f"[llm] 使用模型 {LLM_MODEL} @ {LLM_URL}")

    state = load_state()
    # 人设由 LLM 实时生成；同一昵称的人设会缓存进 bot_state.json，避免重复消耗 token
    personas = []
    for i in range(1, args.agents + 1):
        persona = gen_persona(i)
        cached = state["accounts"].get(persona["nickname"])
        if cached and cached.get("bio"):
            persona["bio"] = cached["bio"]      # 复用旧账号已有简介，保持一致性
        else:
            state.setdefault("personas", {})[persona["nickname"]] = persona["bio"]
        personas.append(persona)
        print(f"[persona] {persona['nickname']}：{persona['bio']}"
              f"（头像描述: {persona.get('avatar_desc') or '无'}）")

    tokens = {}
    for p in personas:
        acc = login_agent(state, p["nickname"], args.dry_run)
        if acc:
            # 注册成功后立即完善资料：昵称/签名 + 从网络找图上传头像
            if not args.no_avatar or args.dry_run:
                setup_profile(acc, p, state, args.dry_run if args.no_avatar else False)
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
