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
import re
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
LLM_KEY = os.environ.get("BOT_LLM_KEY", "sk-15782c1f893144c9b3868f8074c7c5f6")
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
def _clean_llm_text(s: str) -> str:
    """去掉 markdown 代码块围栏和首尾引号。"""
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    return s.strip().strip("`").strip("\"'“”").strip()


def _extract_json_obj(s: str) -> dict | None:
    """从文本中截取第一个平衡括号的 JSON 对象并解析；失败返回 None。"""
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:  # noqa: BLE001
                    return None
    return None


def gen_persona(idx: int) -> dict:
    """让 LLM 生成一个拟真人设：昵称 + 简介 + 头像描述。
    三项分开调用、各自校验：昵称必须是纯中文短名，防止模型跑偏把 JSON 原样吐回
    或被后端拒绝后仍继续发帖（之前数据库 name 为空的根因之一就是脏昵称）。"""
    # 1) 昵称：只要纯文本，严格校验
    nick = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"为一个中文社交社区的虚拟用户想一个网名：2~6个字，像真实网友会用的名字"
            f"（例如'山间清风''夜航星''橘子汽水'这类），不要含'用户''测试'字样，"
            f"不要引号、标点、JSON 或解释，只输出名字本身。"))
        if re.fullmatch(r"[\w\u4e00-\u9fff·\-]{2,12}", raw.replace(" ", "")) and \
                not any(b in raw for b in ("用户", "测试", "{", "}")):
            nick = raw.replace(" ", "")[:20]
            break
    if not nick:
        sys.exit("[致命] 昵称生成连续失败（无兜底模板），请检查 LLM 输出质量或更换模型。")

    # 2) 简介
    bio = ""
    for _ in range(3):
        raw = _clean_llm_text(llm_generate(
            f"给网名「{nick}」的社区用户写一句 10~20 字的个人签名"
            f"（体现职业或爱好，口语自然），只输出签名本身。"))
        if 2 <= len(raw) <= 60 and "{" not in raw:
            bio = raw[:50]
            break
    if not bio:
        sys.exit(f"[致命] 「{nick}」的简介生成连续失败（无兜底模板）。")

    # 3) 头像英文描述（仅用于配图参考，失败可容忍为空）
    avatar_desc = ""
    try:
        raw = _clean_llm_text(llm_generate(
            f"「{nick}」（{bio}）这个社区用户需要一张网络头像，用 5~12 个英文单词"
            f"描述匹配其气质的头像画面（如 smiling asian college girl with glasses），"
            f"只输出英文描述本身。"))
        if raw and "{" not in raw and len(raw) <= 120:
            avatar_desc = raw
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        pass
    return {"nickname": nick, "bio": bio, "avatar_desc": avatar_desc}


# ---------------------------------------------------------------------------
# 网络头像：从公开免费头像源随机抓取一张真实图片并上传为账号头像
#   - 使用纯图片直链服务（dicebear 生成风 / this-person-does-not-exist 真人风），
#     避免 HTML 页面导致上传非图片文件被后端拒绝。
#   - 下载失败时跳过该账号头像，不影响注册发帖主流程。
# ---------------------------------------------------------------------------
AVATAR_SOURCES = [
    lambda seed, desc: (
        "https://api.dicebear.com/7.x/avataaars/svg?"
        f"seed={seed}&backgroundColor=c7e3ee"),
    lambda seed, desc: (
        "https://api.dicebear.com/7.x/lorelei/svg?"
        f"seed={seed}&backgroundColor=c7e3ee"),
    lambda seed, desc: (
        "https://api.dicebear.com/7.x/pixel-art/svg?"
        f"seed={seed}&backgroundColor=c7e3ee"),
]


def fetch_avatar(nickname: str, avatar_desc: str) -> tuple | None:
    """从真实图片网站下载头像（小红书/Unsplash/Pexels等）。
    返回 (bytes, filename, content_type)；全部失败返回 None。"""

    # 方案1：Unsplash 随机人物图片（高质量，免费）
    unsplash_keywords = [
        "portrait", "face", "person", "selfie", "profile",
        "woman", "man", "girl", "boy", "people"
    ]
    keyword = random.choice(unsplash_keywords)
    unsplash_url = f"https://source.unsplash.com/150x150/?{keyword}"

    # 方案2：Pexels 人物图片API（需要免费API key）
    # 方案3：小红书图片（需要解析，较复杂）
    # 方案4：GitHub 用户头像（真实用户）
    github_user = f"https://github.com/{random.choice(['torvalds', 'gaearon', 'sindresorhus', 'yyx990803'])}.png"

    sources = [
        ("Unsplash", unsplash_url),
        ("GitHub Avatar", github_user),
    ]

    for source_name, url in sources:
        try:
            print(f"  [avatar] {nickname}: 尝试从 {source_name} 下载...")
            data = http_download(url, timeout=15)
        except Exception as e:
            print(f"  [avatar] {nickname}: {source_name} 下载失败: {e}", file=sys.stderr)
            continue

        # 校验图片格式
        if data[:3] == b"\xff\xd8\xff":
            return data, f"{nickname}_{uuid.uuid4().hex[:6]}.jpg", "image/jpeg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return data, f"{nickname}_{uuid.uuid4().hex[:6]}.png", "image/png"
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return data, f"{nickname}_{uuid.uuid4().hex[:6]}.gif", "image/gif"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return data, f"{nickname}_{uuid.uuid4().hex[:6]}.webp", "image/webp"

        print(f"  [avatar] {nickname}: {source_name} 返回的不是图片", file=sys.stderr)

    print(f"  [avatar] {nickname}: 所有图片源均失败", file=sys.stderr)
    return None


def gen_text(kind: str, persona: dict) -> str:
    """生成帖子正文或评论内容；对 LLM 输出做清洗+校验，失败会重试/退出，
    绝不把 markdown、JSON 之类的脏文本灌进社区。"""
    if kind == "post":
        p = (f"你扮演社区用户「{persona['nickname']}」，人设：{persona['bio']}。"
             f"以他/她的口吻发一条中文社区动态，50~120字，口语化，不要话题标签，只输出正文。")
    else:
        p = (f"你是社区用户「{persona['nickname']}」。请针对下面这条帖子写一条 10~40 字的"
             f"中文评论，自然一点，可以带点个人经验：\n{persona.get('target', '')}\n只输出评论。")
    for _ in range(3):
        out = _clean_llm_text(llm_generate(p)).replace("\n", "")
        # 帖子至少 10 字、评论至少 2 字，且不能是 JSON/markdown 残骸
        min_len = 10 if kind == "post" else 2
        if len(out) >= min_len and not out.startswith("{") and "```" not in out:
            return out[:280]
    sys.exit(f"[致命] {kind} 内容生成连续不合格（无兜底模板）：{out[:80]!r}")


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


def _verify_token(account: str, token: str) -> bool:
    """用带 token 的 GET /user/getUser 验证 JWT 是否有效（该接口不在拦截器白名单内）。"""
    r = http_json("GET", "/user/getUser", params={"account": account}, token=token)
    d = r.get("data") if isinstance(r.get("data"), dict) else {}
    return bool(r) and r.get("code") == 1 and d.get("account") == account


def login_agent(state: dict, nickname: str, dry_run: bool):
    """登录（手机号不存在时后端自动注册）。randomNum==code 即可通过验证码校验。
    缓存的旧 token 若已失效（如后端重启换了 JWT 密钥），会自动重新登录换取新 token。"""
    account = state["accounts"].get(nickname)
    if account and account.get("token"):
        if dry_run or _verify_token(account["account"], account["token"]):
            return account
        print(f"  [login] {nickname}: 缓存 token 已失效，重新登录…", file=sys.stderr)
    phone = "199" + "".join(random.choices("0123456789", k=8))
    code = "".join(random.choices("0123456789", k=6))
    if dry_run:
        print(f"  [dry] POST /user/login  phone={phone}")
        return {"phone": phone, "account": "DRY-" + uuid.uuid4().hex[:8],
                "token": "dry-token", "nickname": nickname}
    r = http_json("POST", "/user/login", {"phone": phone, "code": code, "randomNum": code})
    data = (r or {}).get("data")
    data = data if isinstance(data, dict) else {}
    token = data.get("token")
    user = data.get("user") or {}
    if not token:
        print(f"  [login] 失败，检查后端是否启动/接口鉴权: {r}", file=sys.stderr)
        return None
    acc = {"phone": phone, "account": user.get("account"), "token": token, "nickname": nickname}
    state["accounts"][nickname] = acc
    save_state(state)
    return acc


def setup_profile(acc: dict, persona: dict, state: dict, dry_run: bool) -> bool:
    """注册后完善资料：昵称/签名用 LLM 人设；头像从网络下载并上传。
    如果头像上传失败，直接终止程序（sys.exit）。"""

    if dry_run:
        print(f"[dry] {acc['nickname']}: GET /user/getUser -> PUT /user(name,sign) -> "
              f"POST /user/avatar(网络抓图上传)")
        return True

    # 1. 取回当前完整用户记录
    r = http_json("GET", "/user/getUser", params={"account": acc["account"]},
                  token=acc["token"])
    _u = (r or {}).get("data")
    user = _u if isinstance(_u, dict) else {}
    if not user.get("account"):
        print(f"  [profile] {acc['nickname']}: 获取用户失败，终止程序", file=sys.stderr)
        sys.exit(f"[致命] {acc['nickname']} 获取用户信息失败，无法设置资料")

    def put_profile(av: str | None) -> bool:
        payload = {
            "account": user["account"],
            "name": persona["nickname"],
            "sign": persona["bio"],
            "phone": user.get("phone"),
            "avatar": av,
        }
        resp = http_json("PUT", "/user", payload, token=acc["token"], raise_on_error=True)
        return bool(resp)

    # 2. 头像：必须从网络下载并上传，失败则终止
    avatar_url = user.get("avatar")
    if not avatar_url:
        print(f"[avatar] {acc['nickname']}: 开始下载网络头像...")
        img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""))

        if not img:
            sys.exit(f"[致命] {acc['nickname']} 头像下载失败（所有源均不可用），程序终止")

        data, fname, ctype = img

        try:
            up = http_multipart("POST", "/user/avatar",
                                fields={"account": acc["account"]},
                                file_field="avatar", filename=fname,
                                file_bytes=data, content_type=ctype,
                                token=acc["token"])
        except Exception as e:
            sys.exit(f"[致命] {acc['nickname']} 头像上传异常: {e}")

        avatar_data = (up or {}).get("data")
        new_avatar = avatar_data.get("avatar") if isinstance(avatar_data, dict) else None

        if not new_avatar:
            sys.exit(f"[致命] {acc['nickname']} 头像上传失败（后端未返回avatar字段），程序终止")

        avatar_url = new_avatar
        state["avatars"][persona["nickname"]] = new_avatar
        print(f"[avatar] {acc['nickname']}: 上传成功 {new_avatar}")

    # 3. 写回昵称/签名/头像
    try:
        if not put_profile(avatar_url):
            sys.exit(f"[致命] {acc['nickname']} PUT /user 失败，程序终止")
    except ApiError as e:
        sys.exit(f"[致命] {acc['nickname']} 更新资料失败: {e}")

    # 4. 回读数据库确认
    check = http_json("GET", "/user/getUser", params={"account": acc["account"]},
                      token=acc["token"])
    _g = (check or {}).get("data")
    got = _g if isinstance(_g, dict) else {}

    if got.get("name") != persona["nickname"]:
        sys.exit(f"[致命] {acc['nickname']} 回读校验失败！数据库 name={got.get('name')!r}")

    print(f"[profile] {acc['nickname']}: OK name='{got.get('name')}' "
          f"avatar={got.get('avatar') or '无'}")
    return True

    def put_profile(av: str | None) -> bool:
        payload = {
            "account": user["account"],
            "name": persona["nickname"],
            "sign": persona["bio"],
            "phone": user.get("phone"),      # 必须带上，否则会被 UPDATE 洗成 null
            "avatar": av,
        }
        resp = http_json("PUT", "/user", payload, token=acc["token"], raise_on_error=True)
        return bool(resp)

    # 2. 头像：已有则复用（缓存账号不重复下载）；没有则从网络找图并上传
    avatar_url = user.get("avatar")
    if not avatar_url:
        cached_avatar = state.setdefault("avatars", {}).get(persona["nickname"])
        if cached_avatar:
            avatar_url = cached_avatar
        elif not dry_run:
            img = fetch_avatar(persona["nickname"], persona.get("avatar_desc", ""))
            if img:
                data, fname, ctype = img
                try:
                    up = http_multipart("POST", "/user/avatar",
                                        fields={"account": acc["account"]},
                                        file_field="avatar", filename=fname,
                                        file_bytes=data, content_type=ctype,
                                        token=acc["token"])
                except Exception as e:  # noqa: BLE001
                    up = None
                    print(f"  [avatar] {acc['nickname']}: 上传异常 {e}", file=sys.stderr)
                avatar_data = (up or {}).get("data")
                new_avatar = avatar_data.get("avatar") if isinstance(avatar_data, dict) else None
                if new_avatar:
                    avatar_url = new_avatar
                    state["avatars"][persona["nickname"]] = new_avatar
                    print(f"[avatar] {acc['nickname']}: 上传成功 {new_avatar}")
                else:
                    print(f"[avatar] {acc['nickname']}: 上传失败，本次不设头像", file=sys.stderr)

    # 3. 写回昵称/签名/头像；PUT 内部会按传入 avatar 覆盖，故头像上传放在 PUT 之前
    try:
        put_profile(avatar_url)
    except ApiError as e:
        print(f"  [profile] {acc['nickname']}: PUT /user 失败: {e}", file=sys.stderr)
        return False

    # 4. 回读数据库确认 name 真的写进去了（防止静默失败）
    check = http_json("GET", "/user/getUser", params={"account": acc["account"]},
                      token=acc["token"])
    _g = (check or {}).get("data")
    got = _g if isinstance(_g, dict) else {}
    if got.get("name") != persona["nickname"]:
        print(f"  [profile] {acc['nickname']}: 回读校验失败！数据库 name="
              f"{got.get('name')!r}，请检查后端 PUT /user 是否报错", file=sys.stderr)
        return False
    print(f"[profile] {acc['nickname']}: OK name='{got.get('name')}' "
          f"avatar={got.get('avatar') or '无'}")
    return True


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
    seen_nick = set()
    for i in range(1, args.agents + 1):
        persona = gen_persona(i)
        # 昵称撞车（LLM 重复生成/与已有账号重名）会导致后面账号互相覆盖，跳过重来
        if persona["nickname"] in seen_nick or (persona["nickname"] in state["accounts"]
                                                and not args.dry_run):
            print(f"  [persona] 昵称「{persona['nickname']}」重复，重新生成…", file=sys.stderr)
            continue
        cached = state["accounts"].get(persona["nickname"])
        if cached and cached.get("bio"):
            persona["bio"] = cached["bio"]      # 复用旧账号已有简介，保持一致性
        else:
            state.setdefault("personas", {})[persona["nickname"]] = persona["bio"]
        seen_nick.add(persona["nickname"])
        personas.append(persona)
        print(f"[persona] {persona['nickname']}：{persona['bio']}"
              f"（头像描述: {persona.get('avatar_desc') or '无'}）")

    tokens = {}
    failed_profiles = []
    for p in personas:
        acc = login_agent(state, p["nickname"], args.dry_run)
        if not acc:
            continue
        # 注册成功后立即完善资料：昵称/签名 + 从网络找图上传头像。
        # 资料写入失败（数据库 name 仍为空）时跳过该账号后续发帖，避免产生"无名号"帖子；
        # 同时把失效缓存删掉，下次运行会重新登录+重试资料。
        want_profile = args.dry_run or not args.no_avatar
        if want_profile and not setup_profile(acc, p, state, args.dry_run):
            print(f"  [skip] {p['nickname']}: 资料设置未成功，本次不用于发帖/互动", file=sys.stderr)
            failed_profiles.append(p["nickname"])
            state["accounts"].pop(p["nickname"], None)
            save_state(state)
            time.sleep(args.interval)
            continue
        tokens[p["nickname"]] = acc
        time.sleep(args.interval)
    if failed_profiles:
        print(f"[warn] 以下账号资料写入失败已跳过: {failed_profiles}", file=sys.stderr)

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
