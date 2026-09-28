const app = document.querySelector("#app");
const nav = document.querySelector("#nav");
const routes = [
  { id: "home", icon: "home", label: "首页" },
  { id: "discover", icon: "search", label: "探索" },
  { id: "compose", icon: "add", label: "发布" },
  { id: "messages", icon: "list", label: "消息" },
  { id: "profile", icon: "me", label: "我的" },
];
const initialHash = location.hash.slice(1) || "home";
const initialProfile = initialHash.match(/^profile\/(.+)$/);
let state = {
  route: initialProfile ? "profile" : initialHash,
  profileAccount: initialProfile ? decodeURIComponent(initialProfile[1]) : null,
  user: JSON.parse(localStorage.getItem("bowall.user") || "null"),
  token: localStorage.getItem("bowall.token"),
  chat: null,
  unreadMessages: 0,
};
if (!state.token) state.user = null;
const avatar = (user) =>
  user?.avatar ||
  `https://api.dicebear.com/9.x/initials/svg?seed=${encodeURIComponent(user?.name || user?.phone || "Bo")}`;
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
      ...(options.headers || {}),
    },
  });
  const body = await res.json();
  if (!res.ok || body.code !== 1) throw new Error(body.msg || "请求失败");
  return body.data;
}
function uploadImage(form) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/image/post");
    if (state.token)
      xhr.setRequestHeader("Authorization", `Bearer ${state.token}`);
    xhr.onload = () => {
      try {
        const result = JSON.parse(xhr.responseText);
        if (xhr.status >= 200 && xhr.status < 300 && result.code === 1)
          resolve(result.data);
        else
          reject(new Error(result.msg || `图片上传失败（HTTP ${xhr.status}）`));
      } catch {
        reject(new Error(`图片上传失败（HTTP ${xhr.status}）`));
      }
    };
    xhr.onerror = () =>
      reject(new Error("图片网络上传失败，请确认后端仍在运行"));
    xhr.send(form);
  });
}
function toast(message) {
  const el = document.querySelector("#toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2200);
}
function renderNav() {
  nav.innerHTML = routes
    .map(
      (r) => {
        const unread = r.id === "messages" ? state.unreadMessages : 0;
        const badge = unread ? `<span class="nav-badge ${unread > 99 ? "dot" : ""}">${unread > 99 ? "" : unread}</span>` : "";
        return `<button class="nav-item ${state.route === r.id ? "active" : ""}" data-route="${r.id}"><i><img src="/assets/icon/${r.icon}${state.route === r.id ? "_selected" : ""}.png" alt="">${badge}</i>${r.label}</button>`;
      },
    )
    .join("");
}
async function refreshUnreadMessages() {
  if (!state.user || !state.token) return;
  try {
    const conversations = await api(`/message/notification?account=${encodeURIComponent(state.user.account)}`);
    state.unreadMessages = (conversations || []).reduce((total, item) => total + Number(item.count || 0), 0);
    renderNav();
  } catch {
    // The navigation remains usable if the badge request is temporarily unavailable.
  }
}
function empty(title, copy) {
  return `<section class="card empty"><strong>${title}</strong><span>${copy}</span></section>`;
}
async function home() {
  app.innerHTML = `<header class="page-head"><div><h1>博墙</h1><p>记录此刻，也看见彼此。</p></div><button class="primary" data-route="compose">发布</button></header><div id="feed" class="feed">${empty("正在加载…", "")}</div>`;
  try {
    const posts = await api(
      `/posts/getAllPosts?page=1&size=20&account=${encodeURIComponent(state.user.account)}`,
    );
    document.querySelector("#feed").innerHTML = posts.length
      ? posts.map(postCard).join("")
      : empty("还没有动态", "成为第一个发布内容的人吧。");
  } catch (e) {
    document.querySelector("#feed").innerHTML = empty(
      "动态加载失败",
      esc(e.message),
    );
  }
}
function compose() {
  let files = [];
  app.innerHTML = `<header class="page-head compose-head"><div><p class="eyebrow">新动态</p><h1>说说现在的想法</h1></div></header><section class="card composer twitter-compose"><img class="avatar compose-avatar" src="${avatar(state.user)}" alt=""><div class="compose-main"><textarea id="post-text" maxlength="1000" placeholder="有什么新鲜事？"></textarea><div id="image-preview" class="image-preview"></div><div class="compose-bar"><label class="image-picker" title="添加图片"><span>▧</span><input id="post-images" type="file" accept="image/png,image/jpeg,image/gif" multiple></label><span class="compose-rule"></span><span id="publish-state" class="hint">最多 9 张图片</span><button id="send-post" class="primary">发布</button></div></div></section>`;
  const preview = document.querySelector("#image-preview");
  function renderImages() {
    preview.innerHTML = files
      .map(
        (file, index) =>
          `<div><img src="${URL.createObjectURL(file)}" alt="待上传图片"><button type="button" data-remove-image="${index}">×</button></div>`,
      )
      .join("");
  }
  document.querySelector("#post-images").onchange = (e) => {
    files = [...files, ...e.target.files].slice(0, 9);
    renderImages();
  };
  preview.onclick = (e) => {
    const button = e.target.closest("[data-remove-image]");
    if (button) {
      files.splice(Number(button.dataset.removeImage, 10), 1);
      renderImages();
    }
  };
  document.querySelector("#send-post").onclick = async () => {
    const text = document.querySelector("#post-text").value.trim();
    if (!text && !files.length) return toast("写点内容或选择图片再发送吧");
    const stateLabel = document.querySelector("#publish-state");
    try {
      stateLabel.textContent = "正在发布…";
      const postId = await api("/posts/post", {
        method: "POST",
        body: JSON.stringify({
          account: state.user.account,
          text: text || "图片动态",
        }),
      });
      for (let i = 0; i < files.length; i++) {
        stateLabel.textContent = `正在上传图片 ${i + 1}/${files.length}…`;
        const form = new FormData();
        form.append("account", state.user.account);
        form.append("postId", postId);
        form.append("images", files[i]);
        await uploadImage(form);
      }
      toast("已发布");
      go("home");
    } catch (e) {
      stateLabel.textContent = "";
      toast(e.message);
    }
  };
}
async function discover() {
  app.innerHTML = `<header class="page-head"><div><h1>探索</h1><p>搜索感兴趣的内容。</p></div></header><form id="search" class="searchbar"><input id="q" placeholder="搜索动态或账号"><button class="primary">搜索</button></form><div id="results" class="search-results"></div>`;
  document.querySelector("#search").onsubmit = async (e) => {
    e.preventDefault();
    const q = document.querySelector("#q").value;
    try {
      const posts = await api(
        `/posts/getPostsPages?page=1&size=30&inValue=${encodeURIComponent(q)}`,
      );
      const r = document.querySelector("#results");
      r.innerHTML =
        posts
          .flatMap((p) =>
            (p.images || []).map(
              (i) =>
                `<button data-profile="${esc(p.account)}" title="查看 @${esc(p.account)} 的主页"><img src="${esc(i.url)}" alt="${esc(p.text)}"><span>@${esc(p.account)}</span></button>`,
            ),
          )
          .join("") || empty("没有图片动态", "试试换一个关键词。");
    } catch (e) {
      toast(e.message);
    }
  };
}
async function messages() {
  app.innerHTML = `<header class="page-head"><div><h1>消息</h1><p>和朋友聊聊最近的动态。</p></div></header><section class="card friends-panel"><div class="section-title"><b>互关好友</b><span id="friend-count">加载中…</span></div><div id="friend-list" class="friend-list"></div></section><section class="message-list conversation-list"><button id="interaction-entry" class="card interaction-entry"><span class="interaction-icon">♡</span><span><b>互动消息</b><small id="interaction-summary">正在加载评论与回复…</small></span><i id="interaction-badge" class="badge" hidden></i><span class="interaction-arrow">›</span></button><section id="interaction-feed" class="interaction-feed" hidden></section><div id="conversation-list">${empty("正在加载…", "")}</div></section>`;
  try {
    const [friendGroups, list, commentNotifications] = await Promise.all([
      api(`/user/friends?account=${encodeURIComponent(state.user.account)}`),
      api(`/message/notification?account=${encodeURIComponent(state.user.account)}`),
      api(`/comments/notification?account=${encodeURIComponent(state.user.account)}`).catch(() => []),
    ]);
    const interactions = (commentNotifications || []).filter((item) => item.account !== state.user.account);
    updateInteractionSummary(interactions);
    document.querySelector("#interaction-entry").onclick = () => showInteractions(interactions);
    const friends = Object.values(friendGroups || {})
      .flat()
      .filter((user) => user && user.account !== state.user.account)
      .filter((user, index, users) => users.findIndex((item) => item.account === user.account) === index);
    document.querySelector("#friend-count").textContent = friends.length ? `${friends.length} 位好友` : "暂无互关好友";
    document.querySelector("#friend-list").innerHTML = friends.length
      ? friends.map((user) => `<button class="friend-item" data-chat="${esc(user.account)}" data-name="${esc(user.name || user.account)}"><img class="avatar" src="${avatar(user)}" alt=""><span>${esc(user.name || "好友")}</span></button>`).join("")
      : `<div class="friends-empty">互相关注后，好友会显示在这里。</div>`;
    document.querySelector("#conversation-list").innerHTML = list.length
      ? list
          .map(
            (m) =>
              `<button class="card message-row" data-chat="${m.account}" data-name="${esc(m.name || m.account)}"><img class="avatar" src="${avatar(m)}" alt=""><span><b>${esc(m.name || m.account)}</b><span class="preview">${esc(m.message?.content || "")}</span></span>${m.count ? `<i class="badge">${m.count}</i>` : ""}</button>`,
          )
          .join("")
      : empty("暂无消息", friends.length ? "点击上方好友，发起第一条私信吧。" : "先互相关注，再开始聊天吧。");
  } catch (e) {
    document.querySelector("#friend-count").textContent = "加载失败";
    document.querySelector("#friend-list").innerHTML = "";
    document.querySelector("#conversation-list").innerHTML = empty(
      "消息加载失败",
      esc(e.message),
    );
  }
}

function showInteractions(interactions) {
  const feed = document.querySelector("#interaction-feed");
  if (!feed) return;
  feed.hidden = !feed.hidden;
  if (feed.hidden) return;
  feed.innerHTML = interactions.length ? interactions.map((item) => {
    const comment = item.comments || {};
    const action = item.replyToName ? `回复了 ${esc(item.replyToName)}` : "评论了你的动态";
    return `<button class="card interaction-row" data-interaction-post="${esc(item.postId)}" data-interaction-comment="${esc(comment.id)}"><img class="avatar" src="${avatar({ avatar: item.userAvatar, name: item.name })}" alt=""><span><b>${esc(item.name || "用户")}</b><small>${action} · ${formatPostTime(comment.updateDate)}</small><em>${esc(comment.text)}</em></span>${item.postsImage ? `<img class="interaction-cover" src="${esc(item.postsImage)}" alt="动态图片">` : ""}</button>`;
  }).join("") : empty("暂无互动消息", "收到评论或回复后会显示在这里。");
  feed.querySelectorAll("[data-interaction-post]").forEach((button) => {
    button.onclick = async () => {
      const commentId = button.dataset.interactionComment;
      try {
        await api(`/comments/${encodeURIComponent(commentId)}/read`, { method: "PUT" });
        const interaction = interactions.find((item) => item.comments?.id === commentId);
        if (interaction?.comments) interaction.comments.isRead = "yes";
        updateInteractionSummary(interactions);
      } catch (error) {
        toast(error.message);
      }
      showInteractionDetail(button.dataset.interactionPost, commentId);
    };
  });
}

function updateInteractionSummary(interactions) {
  const summary = document.querySelector("#interaction-summary");
  const badge = document.querySelector("#interaction-badge");
  if (!summary || !badge) return;
  const unread = interactions.filter((item) => item.comments?.isRead !== "yes").length;
  summary.textContent = interactions.length ? `${interactions.length} 条评论或回复` : "暂无互动消息";
  badge.hidden = !unread;
  badge.textContent = unread > 99 ? "99+" : unread;
}

async function showInteractionDetail(postId, commentId) {
  try {
    const post = await api(`/posts/getPostsById?postId=${encodeURIComponent(postId)}`);
    const commentDto = (post.comments || []).find((item) => item.comments?.id === commentId);
    const comment = commentDto?.comments;
    const modal = document.createElement("div");
    modal.className = "interaction-modal";
    modal.innerHTML = `<section class="interaction-dialog"><button class="modal-close" aria-label="关闭">×</button><p class="eyebrow">互动消息</p>${comment ? `<div class="interaction-detail"><img class="avatar" src="${avatar({ avatar: commentDto.userAvatar, name: commentDto.name })}" alt=""><div><b>${esc(commentDto.name || "用户")}${commentDto.replyToName ? ` 回复 ${esc(commentDto.replyToName)}` : " 评论了你的动态"}</b><p>${esc(comment.text)}</p></div></div><form id="interaction-reply" class="interaction-reply"><input name="content" maxlength="300" placeholder="回复 ${esc(commentDto.name || "这条评论")}…"><button class="primary">回复</button></form>` : ""}<div class="source-post"><div class="post-top"><img class="avatar" src="${avatar(post.user)}" alt=""><b>${esc(post.user?.name || post.account)}</b></div><p>${esc(post.text)}</p>${post.images?.[0] ? `<img src="${esc(post.images[0].url)}" alt="动态图片">` : ""}</div></section>`;
    document.body.append(modal);
    modal.onclick = (event) => { if (event.target === modal || event.target.closest(".modal-close")) modal.remove(); };
    const replyForm = modal.querySelector("#interaction-reply");
    if (replyForm && comment) {
      replyForm.onsubmit = async (event) => {
        event.preventDefault();
        const content = replyForm.elements.content.value.trim();
        if (!content) return;
        try {
          await api("/comments/post", { method: "POST", body: JSON.stringify({ postsId: post.id, account: state.user.account, comments: content, parentId: comment.id, replyToAccount: comment.account }) });
          toast("回复已发送");
          modal.remove();
        } catch (error) {
          toast(error.message);
        }
      };
    }
  } catch (error) {
    toast(error.message);
  }
}
async function profile(account = state.profileAccount || state.user.account) {
  const isMine = account === state.user.account;
  app.innerHTML = `<section class="card profile"><div class="profile-top"><img class="avatar" src="${avatar({ account })}" alt=""><div><h1>正在加载…</h1><p>个人主页</p></div></div><div class="stats" id="stats"><span><b>–</b>动态</span><span><b>–</b>粉丝</span><span><b>–</b>关注</span></div><div id="profile-actions" class="profile-actions"></div></section><div id="mine" class="feed" style="margin-top:16px"></div>`;
  try {
    const [u, p, f, fo, posts, followsTarget, targetFollowsMe] = await Promise.all([
      api(`/user/getUser?account=${encodeURIComponent(account)}`),
      api(`/posts/count?account=${encodeURIComponent(account)}`),
      api(`/fans/count?account=${encodeURIComponent(account)}`),
      api(`/followers/count?account=${encodeURIComponent(account)}`),
      api(`/posts/getPosts?account=${encodeURIComponent(account)}`),
      isMine ? Promise.resolve(null) : api(`/fans/isfan?account=${encodeURIComponent(account)}&fansAccount=${encodeURIComponent(state.user.account)}`),
      isMine ? Promise.resolve(null) : api(`/fans/isfan?account=${encodeURIComponent(state.user.account)}&fansAccount=${encodeURIComponent(account)}`),
    ]);
    document.querySelector(".profile-top").innerHTML = `<img class="avatar" src="${avatar(u)}" alt="${esc(u.name || "用户")}的头像"><div><h1>${esc(u.name || u.account)}</h1><p>${esc(u.sign || "这个人还没有留下签名。")}</p></div>`;
    document.querySelector("#stats").innerHTML =
      `<span><b>${p}</b>动态</span><span><b>${f}</b>粉丝</span><span><b>${fo}</b>关注</span>`;
    document.querySelector("#mine").innerHTML = posts.length
      ? posts.map((post) => postCard({ ...post, user: u })).join("")
      : empty(isMine ? "你还没有动态" : "TA 还没有动态", isMine ? "发布第一条动态，让大家认识你。" : "晚点再来看看吧。");
    const actions = document.querySelector("#profile-actions");
    if (isMine) {
      actions.innerHTML = `<button id="edit-profile" class="primary">编辑主页</button>`;
      document.querySelector("#edit-profile").onclick = editProfile;
    } else {
      const label = followsTarget ? (targetFollowsMe ? "互相关注" : "已关注") : (targetFollowsMe ? "回关" : "关注");
      actions.innerHTML = `<button id="toggle-follow" class="primary ${followsTarget ? "following" : ""}">${label}</button><button id="profile-message" class="quiet action-button">私信</button>`;
      document.querySelector("#toggle-follow").onclick = () => toggleFollow(account);
      document.querySelector("#profile-message").onclick = () => {
        state.chat = { account, name: u.name || u.account };
        state.route = "chat";
        location.hash = "chat";
        render();
      };
    }
  } catch (e) {
    document.querySelector("#mine").innerHTML = empty("主页加载失败", esc(e.message));
  }
}

async function toggleFollow(account) {
  const button = document.querySelector("#toggle-follow");
  if (!button) return;
  button.disabled = true;
  try {
    const result = await api("/user/add", {
      method: "POST",
      body: JSON.stringify({ account, fansAccount: state.user.account }),
    });
    toast(result);
    profile(account);
  } catch (error) {
    toast(error.message);
    button.disabled = false;
  }
}

function openProfile(account) {
  if (!account) return;
  state.profileAccount = account;
  state.route = "profile";
  location.hash = account === state.user.account ? "profile" : `profile/${encodeURIComponent(account)}`;
  render();
}
function openAvatarCropper(file, onDone) {
  const reader = new FileReader();
  reader.onload = () => {
    const image = new Image();
    image.onload = () => {
      let zoom = 1,
        offsetX = 0,
        offsetY = 0,
        drag = null;
      const modal = document.createElement("div");
      modal.className = "crop-modal";
      modal.innerHTML = `<section class="crop-panel"><h2>裁剪头像</h2><p>拖动图片调整位置，使用滑块缩放。保存后将生成 512 × 512 头像。</p><canvas width="512" height="512"></canvas><label class="crop-zoom">缩放 <input type="range" min="1" max="3" step="0.01" value="1"></label><div class="crop-actions"><button class="quiet" type="button">取消</button><button class="primary" type="button">确认裁剪</button></div></section>`;
      document.body.append(modal);
      const canvas = modal.querySelector("canvas"),
        ctx = canvas.getContext("2d"),
        range = modal.querySelector("input"),
        [cancel, confirm] = modal.querySelectorAll("button");
      const base = Math.max(
        canvas.width / image.width,
        canvas.height / image.height,
      );
      function draw() {
        const width = image.width * base * zoom,
          height = image.height * base * zoom;
        const minX = canvas.width - width,
          maxX = 0,
          minY = canvas.height - height,
          maxY = 0;
        offsetX = Math.min(maxX, Math.max(minX, offsetX));
        offsetY = Math.min(maxY, Math.max(minY, offsetY));
        ctx.fillStyle = "#e9e7e2";
        ctx.fillRect(0, 0, 512, 512);
        ctx.drawImage(image, offsetX, offsetY, width, height);
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(256, 256, 252, 0, Math.PI * 2);
        ctx.stroke();
      }
      function point(e) {
        const r = canvas.getBoundingClientRect(),
          p = e.touches?.[0] || e;
        return {
          x: ((p.clientX - r.left) * 512) / r.width,
          y: ((p.clientY - r.top) * 512) / r.height,
        };
      }
      range.oninput = () => {
        zoom = Number(range.value);
        draw();
      };
      canvas.onpointerdown = (e) => {
        drag = point(e);
        canvas.setPointerCapture(e.pointerId);
      };
      canvas.onpointermove = (e) => {
        if (!drag) return;
        const p = point(e);
        offsetX += p.x - drag.x;
        offsetY += p.y - drag.y;
        drag = p;
        draw();
      };
      canvas.onpointerup = () => (drag = null);
      cancel.onclick = () => modal.remove();
      confirm.onclick = () =>
        canvas.toBlob(
          (blob) => {
            modal.remove();
            onDone(new File([blob], "avatar.jpg", { type: "image/jpeg" }));
          },
          "image/jpeg",
          0.92,
        );
      draw();
    };
    image.src = reader.result;
  };
  reader.readAsDataURL(file);
}
function editProfile() {
  const u = state.user;
  let croppedAvatarFile = null;
  app.innerHTML = `<header class="page-head"><div><h1>编辑主页</h1><p>完善你的个人资料。</p></div></header><form id="edit" class="card composer"><div class="field avatar-field"><label>头像</label><img id="avatar-preview" class="avatar avatar-large" src="${avatar(u)}" alt="当前头像"><input id="avatar-file" name="avatar" type="file" accept="image/png,image/jpeg,image/gif,image/webp"><span class="hint">选择图片后可裁剪为正方形头像。</span></div><div class="field"><label>昵称</label><input name="name" value="${esc(u.name)}"></div><div class="field"><label>个性签名</label><input name="sign" value="${esc(u.sign)}"></div><div class="field"><label>手机号</label><input name="phone" value="${esc(u.phone)}"></div><button class="primary">保存修改</button></form>`;
  const fileInput = document.querySelector("#avatar-file");
  fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (file)
      openAvatarCropper(file, (cropped) => {
        croppedAvatarFile = cropped;
        document.querySelector("#avatar-preview").src =
          URL.createObjectURL(cropped);
      });
  };
  document.querySelector("#edit").onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    delete data.avatar;
    const next = { ...u, ...data };
    try {
      await api("/user", { method: "PUT", body: JSON.stringify(next) });
      if (croppedAvatarFile) {
        const form = new FormData();
        form.append("account", u.account);
        form.append("avatar", croppedAvatarFile);
        const response = await fetch("/user/avatar", {
          method: "POST",
          headers: state.token
            ? { Authorization: `Bearer ${state.token}` }
            : {},
          body: form,
        });
        const result = await response.json();
        if (!response.ok || result.code !== 1)
          throw new Error(result.msg || "头像上传失败");
        Object.assign(next, result.data);
      }
      state.user = next;
      localStorage.setItem("bowall.user", JSON.stringify(next));
      toast("资料已保存");
      go("profile");
    } catch (err) {
      toast(err.message);
    }
  };
}
async function chat(account, name) {
  state.chat = { account, name };
  app.innerHTML = `<section class="card chat"><header class="chat-header"><button class="chat-back" data-route="messages" aria-label="返回消息列表">‹</button><div id="chat-contact" class="chat-contact"><img class="avatar" src="${avatar({ name })}" alt=""><span><b>${esc(name)}</b><small>私信聊天</small></span></div></header><div id="chat-stream" class="chat-stream"><p class="hint">正在加载消息…</p></div><form id="chat-send" class="chat-send"><input name="content" maxlength="1000" placeholder="输入消息…" autocomplete="off"><button class="primary">发送</button></form></section>`;
  let peer = { account, name };
  try {
    peer = await api(`/user/getUser?account=${encodeURIComponent(account)}`);
    const contact = document.querySelector("#chat-contact");
    if (contact) contact.innerHTML = `<img class="avatar" src="${avatar(peer)}" alt=""><span><b>${esc(peer.name || peer.account)}</b><small>私信聊天</small></span>`;
  } catch {
    // The conversation itself remains usable when profile data is unavailable.
  }
  async function load() {
    try {
      const d = await api(
        `/message/getMessage?senderAccount=${state.user.account}&recipientAccount=${account}&page=1&size=50`,
      );
      const stream = document.querySelector("#chat-stream");
      if (!stream) return;
      stream.innerHTML = (d.records || []).map((m) => {
        const mine = m.senderAccount === state.user.account;
        const user = mine ? state.user : peer;
        return `<div class="chat-time">${formatPostTime(m.updateDate)}</div><div class="chat-message ${mine ? "mine" : ""}"><img class="avatar" src="${avatar(user)}" alt=""><div><div class="bubble">${esc(m.content)}</div></div></div>`;
      }).join("") || '<p class="hint chat-empty">还没有消息，打个招呼吧。</p>';
      stream.scrollTop = stream.scrollHeight;
    } catch (e) {
      toast(e.message);
    }
  }
  await load();
  try {
    await api("/message/updateIsRead", {
      method: "PUT",
      body: JSON.stringify({ senderAccount: account, recipientAccount: state.user.account }),
    });
    refreshUnreadMessages();
  } catch {
    // Reading a conversation should not be blocked by an unread-state update failure.
  }
  document.querySelector("#chat-send").onsubmit = async (e) => {
    e.preventDefault();
    const input = e.target.content;
    const content = input.value.trim();
    if (!content) return;
    try {
      await api("/message/sendMessage", {
        method: "POST",
        body: JSON.stringify({
          senderAccount: state.user.account,
          recipientAccount: account,
          content,
        }),
      });
      input.value = "";
      load();
    } catch (err) {
      toast(err.message);
    }
  };
}
function login() {
  app.innerHTML = `<section class="card login"><h1>欢迎来到 BoWall</h1><p>使用手机号开始你的博墙。</p><form id="login"><div class="field"><label>手机号</label><input name="phone" required placeholder="请输入手机号"></div><div class="field"><label>验证码</label><input name="code" required placeholder="开发环境可自填任意相同验证码"></div><div class="field"><label>确认验证码</label><input name="randomNum" required placeholder="与上方验证码保持相同"></div><button class="primary">登录 / 注册</button></form><p class="hint">后端当前沿用小程序的验证码校验接口。</p></section>`;
  document.querySelector("#login").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const data = await api("/user/login", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(e.target))),
      });
      state.user = data.user;
      state.token = data.token;
      localStorage.setItem("bowall.user", JSON.stringify(data.user));
      localStorage.setItem("bowall.token", data.token);
      go("home");
    } catch (err) {
      toast(err.message);
    }
  };
}
function go(route) {
  if (route !== "profile") state.profileAccount = null;
  state.route = route;
  location.hash = route;
  render();
}
function render() {
  renderNav();
  refreshUnreadMessages();
  if (!state.user) return login();
  if (state.route === "home") home();
  else if (state.route === "discover") discover();
  else if (state.route === "compose") compose();
  else if (state.route === "messages") messages();
  else if (state.route === "profile") profile();
  else if (state.route === "chat") chat(state.chat.account, state.chat.name);
  else home();
}
document.addEventListener("click", (e) => {
  const target = e.target.closest("[data-route]");
  if (target) go(target.dataset.route);
  const chatButton = e.target.closest("[data-chat]");
  if (chatButton) {
    state.route = "chat";
    state.chat = {
      account: chatButton.dataset.chat,
      name: chatButton.dataset.name,
    };
    render();
  }
  const profileButton = e.target.closest("[data-profile]");
  if (profileButton) openProfile(profileButton.dataset.profile);
  const like = e.target.closest("[data-like]");
  if (like)
    api("/like", {
      method: "POST",
      body: JSON.stringify({
        account: state.user.account,
        postId: like.dataset.like,
      }),
    })
      .then(() => {
        render();
      })
      .catch((x) => toast(x.message));

  const deleteButton = e.target.closest("[data-delete]");
  if (deleteButton) deletePost(deleteButton.dataset.delete);
});

async function deletePost(postId) {
  if (!window.confirm("确定删除这条动态吗？删除后无法恢复。")) return;

  try {
    await api(
      `/posts/delete/${postId}?account=${encodeURIComponent(state.user.account)}`,
      { method: "DELETE" },
    );
    toast("动态已删除");
    render();
  } catch (error) {
    toast(error.message);
  }
}

document.querySelector("#logout").onclick = () => {
  localStorage.removeItem("bowall.user");
  localStorage.removeItem("bowall.token");
  state.user = null;
  state.token = null;
  go("home");
};
window.addEventListener("hashchange", () => {
  const hash = location.hash.slice(1) || "home";
  const profileMatch = hash.match(/^profile\/(.+)$/);
  state.profileAccount = profileMatch ? decodeURIComponent(profileMatch[1]) : null;
  state.route = profileMatch ? "profile" : hash;
  render();
});
render();
function formatPostTime(value) {
  const date = new Date(value || Date.now());
  if (Number.isNaN(date.getTime())) return "刚刚";
  const isCurrentYear = date.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat("zh-CN", {
    ...(isCurrentYear ? {} : { year: "numeric" }),
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function postCard(post) {
  const user = post.user || { account: post.account, name: post.account };
  const imageList = post.images || [];
  const images = imageList
    .map((i) => `<img data-preview-image src="${esc(i.url)}" alt="动态图片">`)
    .join("");
  const comments = (post.comments || [])
    .slice(0, 3)
    .map((c) => {
      const comment = c.comments || {};
      const author = esc(c.name || "用户");
      const reply = c.replyToName ? ` 回复 <b>${esc(c.replyToName)}</b>` : "";
      return `<div class="comment-line"><button class="profile-link" data-profile="${esc(c.account || comment.account)}"><b>${author}</b></button>${reply}：${esc(comment.text)}<button class="reply-button" data-reply="${esc(comment.id)}" data-reply-account="${esc(comment.account)}" data-reply-name="${author}">回复</button></div>`;
    })
    .join("");
  const imageClass =
    [
      "",
      "one",
      "two",
      "three",
      "four",
      "five",
      "six",
      "seven",
      "eight",
      "nine",
    ][imageList.length] || "nine";
  const canDelete = post.account === state.user.account;

  return `
    <article class="card post">
      <div class="post-top">
        <button class="profile-link" data-profile="${esc(user.account || post.account)}"><img class="avatar" src="${avatar(user)}" alt="查看 ${esc(user.name || user.account || "用户")} 的主页"></button>
        <div>
          <button class="profile-link profile-name" data-profile="${esc(user.account || post.account)}"><b>${esc(user.name || user.account || "匿名用户")}</b></button>
          <small>${formatPostTime(post.updateDate)}</small>
        </div>
      </div>
      <div class="post-text">${esc(post.text)}</div>
      ${images ? `<div class="post-images ${imageClass}">${images}</div>` : ""}
      <div class="post-actions">
        <button data-like="${post.id}">
          <img class="action-icon" src="/assets/interact/${post.isLike ? "liked" : "like"}.png" alt="">
          ${post.isLike ? "已赞" : "赞"}${post.likeCount ? ` ${post.likeCount}` : ""}
        </button>
        <button data-comment="${post.id}">
          <img class="action-icon" src="/assets/interact/message.png" alt="">
          评论
        </button>
        <button data-share="${post.id}">
          <img class="action-icon" src="/assets/interact/forward.png" alt="">
          转发
        </button>
        ${canDelete ? `<button class="danger" data-delete="${post.id}">删除</button>` : ""}
        ${imageList.length > 1 ? `<span class="image-count">${imageList.length} 张图片</span>` : ""}
      </div>
      <form class="post-comment-form" data-comment-form="${post.id}" hidden>
        <input name="comment" maxlength="300" placeholder="写下你的评论…">
        <button>发送</button>
      </form>
      ${comments ? `<div class="comments">${comments}</div>` : ""}
    </article>`;
}
function previewImage(src) {
  const modal = document.createElement("div");
  modal.className = "lightbox";
  modal.innerHTML = `<img src="${esc(src)}" alt="图片预览"><button aria-label="关闭预览">×</button>`;
  document.body.append(modal);
  modal.onclick = (e) => {
    if (e.target === modal || e.target.tagName === "BUTTON") modal.remove();
  };
  document.addEventListener("keydown", function close(e) {
    if (e.key === "Escape") {
      modal.remove();
      document.removeEventListener("keydown", close);
    }
  });
}
document.addEventListener("click", (e) => {
  const image = e.target.closest("[data-preview-image]");
  if (image) {
    previewImage(image.currentSrc || image.src);
    return;
  }
  const comment = e.target.closest("[data-comment]");
  if (comment) {
    const form = document.querySelector(
      `[data-comment-form="${comment.dataset.comment}"]`,
    );
    if (form) {
      form.hidden = !form.hidden;
      if (!form.hidden) form.querySelector("input").focus();
    }
    return;
  }
  const reply = e.target.closest("[data-reply]");
  if (reply) {
    const post = reply.closest(".post");
    const form = post && post.querySelector("[data-comment-form]");
    if (form) {
      form.hidden = false;
      form.dataset.parentId = reply.dataset.reply;
      form.dataset.replyToAccount = reply.dataset.replyAccount;
      form.querySelector("input").placeholder = `回复 ${reply.dataset.replyName}…`;
      form.querySelector("input").focus();
    }
    return;
  }
  const share = e.target.closest("[data-share]");
  if (share) {
    navigator.clipboard
      ?.writeText(`${location.origin}/#home`)
      .then(() => toast("主页链接已复制"))
      .catch(() => toast("可从地址栏复制链接分享"));
  }
});
document.addEventListener("submit", async (e) => {
  const form = e.target.closest("[data-comment-form]");
  if (!form) return;
  e.preventDefault();
  const input = form.elements.comment,
    comments = input.value.trim();
  if (!comments) return;
  try {
    await api("/comments/post", {
      method: "POST",
      body: JSON.stringify({
        postsId: form.dataset.commentForm,
        account: state.user.account,
        comments,
        parentId: form.dataset.parentId || null,
        replyToAccount: form.dataset.replyToAccount || null,
      }),
    });
    toast("评论已发送");
    input.value = "";
    delete form.dataset.parentId;
    delete form.dataset.replyToAccount;
    input.placeholder = "写下你的评论…";
    form.hidden = true;
    render();
  } catch (err) {
    toast(err.message);
  }
});
