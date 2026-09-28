# BoWall 0.5.2 接口协议

本文档整理 BoWall 0.5.2 的 HTTP 与 WebSocket 接口。HTTP 接口统一使用 `R<T>` 响应包装；需要登录的接口通过 JWT 拦截器校验身份。

## 统一响应

```json
{
  "code": 1,
  "msg": null,
  "data": {},
  "map": {}
}
```

`code=1` 表示成功，`code=0` 或其他值表示失败。成功响应通常通过 `R.success(data)` 构造，失败响应通过 `R.error(message)` 构造。

## 认证

受保护请求需要携带 JWT。服务端从请求上下文中读取当前账号，前端请求通常使用 `Authorization: Bearer <token>`。具体拦截范围和过期策略以 `filter/JwtAuthInterceptor.java` 为准。

## HTTP 接口

### 动态 `/posts`

#### `POST /posts/{postId}/view`

记录一次帖子浏览。前端在帖子可视面积达到约 55% 时调用，同一页面会话由前端去重。

返回：`data` 为最新浏览数。

#### `POST /posts/{postId}/dwell`

上报当前浏览会话的有效停留时长。只有帖子达到可视条件且页面处于前台时累计；单次上报最多 300 秒，同一帖子/账号/会话最多累计 1800 秒。

请求体：

```json
{
  "sessionId": "browser-session-id",
  "seconds": 12
}
```

返回：`data` 为当前会话已写入的累计秒数。

#### `GET /posts/{postId}/quality`

仅帖子作者可查看质量统计，返回浏览次数、有效阅读率、快速划走率、平均/中位停留时长、点赞率、评论率、预期停留时长和停留评分。

#### `GET /posts/recommendations?account={account}&page=1&size=20&mode=quality`

返回推荐动态。`mode=quality` 使用可解释规则评分；`mode=time` 使用发布时间倒序，作为快速回退模式。每条帖子可包含 `recommendation`：总分、归一化指标、加权贡献、基础分和探索加分。

### 评论 `/comments`

#### `POST /comments/post`

发表评论或回复评论。

```json
{
  "postsId": "post-id",
  "account": "account",
  "comments": "评论内容",
  "parentId": "parent-comment-id",
  "replyToAccount": "target-account"
}
```

`parentId`、`replyToAccount` 可选；传入父评论时服务端会建立回复关系。

#### `GET /comments/notification?account={account}`

获取当前账号收到的评论互动通知。

### 点赞 `/like`

#### `POST /like`

点赞或取消点赞：

```json
{
  "account": "account",
  "postId": "post-id"
}
```

#### `GET /like/notification?account={account}`

获取当前账号收到的点赞互动通知，不包含自己给自己帖子的点赞。

### 关注 `/followers`

- `GET /followers/getFollowers?account={account}`：获取关注列表。
- `GET /followers/count?account={account}`：获取关注数量。

### 粉丝 `/fans`

粉丝关系相关接口以 `FansController` 当前源码为准。

### 图片 `/image`

- `GET /image/getImage?account={account}`：获取账号上传的图片记录。
- `POST /image/post`：使用 `multipart/form-data` 上传图片。

上传字段：`images`（文件）、`account`（账号）、`postId`（关联帖子 ID）。支持 JPG、JPEG、PNG、GIF。

### 二维码 `/qrcode`

#### `GET /qrcode/{text}`

生成 500×500 的 Base64 PNG 二维码。该接口直接返回图片字符串，不使用 `R` 包装。

### 私信 `/message`

私信列表和聊天记录接口以 `MessageController` 当前源码为准。

### 通知 `/notification`

系统通知查询和标记接口以 `NotificationController` 当前源码为准。

## WebSocket

连接地址：

```text
ws://<host>:<port>/myWebSocket
```

客户端发送 JSON 字符串。首次连接可发送空消息注册会话：

```json
{
  "senderAccount": "current-account",
  "recipientAccount": "",
  "content": ""
}
```

发送私信：

```json
{
  "senderAccount": "sender-account",
  "recipientAccount": "recipient-account",
  "content": "消息内容"
}
```

在线接收方会收到转发消息；当前 WebSocket 通道不负责离线消息持久化，离线消息需通过 HTTP 私信接口落库。

## 接口速查

| 模块 | 方法 | 路径 |
|---|---|---|
| 动态 | POST | `/posts/{postId}/view` |
| 动态 | POST | `/posts/{postId}/dwell` |
| 动态 | GET | `/posts/{postId}/quality` |
| 动态 | GET | `/posts/recommendations` |
| 评论 | POST | `/comments/post` |
| 评论 | GET | `/comments/notification` |
| 点赞 | POST | `/like` |
| 点赞 | GET | `/like/notification` |
| 关注 | GET | `/followers/getFollowers` |
| 关注 | GET | `/followers/count` |
| 图片 | GET | `/image/getImage` |
| 图片 | POST | `/image/post` |
| 二维码 | GET | `/qrcode/{text}` |
| WebSocket | — | `/myWebSocket` |

