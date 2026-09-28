# BoWall Java 后端

BoWall 是配套微信小程序的社交内容后端，基于 Spring Boot 4、MyBatis-Plus、MySQL、Redis 与 WebSocket，并内置一套可直接访问的 Web 前端。

## 技术栈

- Java 26
- Spring Boot 4.1.1（Spring Framework 7）
- MyBatis-Plus 3.5.17（Spring Boot 4 专用 starter）
- MySQL 8.x、Druid 连接池
- Redis
- springdoc OpenAPI 3（Swagger UI）
- WebSocket
- Maven 3.9+

## 项目结构

```text
src/main/java/com/ferry/bowall/
├── common/       # 统一响应、异常处理、基础工具
├── config/       # MVC、Redis、MyBatis-Plus、WebSocket 与 API 文档配置
├── controller/   # HTTP / WebSocket 接口
├── dto/          # 接口传输对象
├── entity/       # 数据库实体
├── enums/        # 业务枚举
├── filter/       # 登录校验
├── mapper/       # MyBatis Mapper
├── service/      # 业务接口与实现
└── Utils/        # 通用工具类（保留原包名以避免破坏现有引用）

src/main/resources/
├── mapper/         # MyBatis XML 映射文件
├── static/         # Web 前端（index.html、app.css、app.js、assets/）
├── db/schema.sql   # 建表脚本（9 张业务表）
└── application.yml # 主配置（含 multipart 上传上限）

src/test/            # 部分测试会连接真实数据库或本机图片路径，默认不应直接运行

docs/                # 版本化接口协议与开发文档
```

## 本地启动

接口协议详见：[BoWall 0.5.2 接口协议](docs/API_PROTOCOL_0.5.2.md)

### 1. 环境要求

- JDK 26
- Maven 3.9+
- MySQL 8.x（默认端口 3306）
- Redis（默认端口 6379）

### 2. 初始化数据库

创建数据库并导入建表脚本：

```sql
CREATE DATABASE IF NOT EXISTS bowall
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
```

```powershell
mysql -u root -p bowall < src/main/resources/db/schema.sql
```

会创建以下 9 张空表：`user`、`posts`、`comments`、`image`、`likes`、`message`、`notification`、`followers`、`fans`。

### 3. 配置环境变量

在 PowerShell 中设置：

```powershell
$env:BOWALL_DB_URL = 'jdbc:mysql://127.0.0.1:3306/bowall?serverTimezone=Asia/Shanghai&useUnicode=true&characterEncoding=utf-8&zeroDateTimeBehavior=convertToNull&useSSL=false&allowPublicKeyRetrieval=true'
$env:BOWALL_DB_USERNAME = 'root'
$env:BOWALL_DB_PASSWORD = 'your-password'
$env:BOWALL_REDIS_HOST = '127.0.0.1'
$env:BOWALL_REDIS_PORT = '6379'
$env:BOWALL_REDIS_PASSWORD = 'your-password'
```

也可以把本机私有配置放到 `src/main/resources/application-local.yml`。该文件已被 Git 忽略，不会被提交：

```yaml
spring:
  datasource:
    password: your-password
  data:
    redis:
      password: your-password
```

### 4. 运行

```powershell
mvn spring-boot:run
```

构建（跳过会访问外部依赖的历史测试）：

```powershell
mvn -DskipTests package
```

启动成功后：

- Web 前端：http://localhost:8080/
- Swagger UI：http://localhost:8080/swagger-ui.html
- OpenAPI JSON：http://localhost:8080/v3/api-docs

## 配置文件说明

- 主配置：`src/main/resources/application.yml`
- 可复制的变量模板与字段说明：`src/main/resources/application-example.yml`
- 本机私有配置（被 Git 忽略）：`src/main/resources/application-local.yml`
- 图片上传目录默认为项目下的 `uploads/`，通过 `/images/{文件名}` 提供访问
- 上传限制：单文件 20MB，单次请求 100MB
- Maven 本地缓存与 settings：`.mvn/settings.xml`、`.mvn/maven.config`

## Web 前端

后端内置一套响应式 Web 前端，启动后访问 `http://localhost:8080/` 即可使用：

- 手机号登录 / 自动注册
- 首页动态流、点赞、评论、图片九宫格与沉浸式预览
- 搜索探索
- 图文发布（最多 9 张图，本地预览、逐张上传）
- 头像上传与 1:1 裁剪（输出 512×512）
- 私信列表与聊天
- 个人主页、统计与资料编辑
- 删除自己的动态（级联清理评论、点赞、图片记录）
- 桌面侧栏 + 手机底部导航

## AI 社区模拟器

模拟器位于 `tools/ai_community_bot.py`，只会向配置了 `name`、`url`、`key` 和 `model` 的 LLM provider 分配账号。运行前至少配置一个 provider：

```powershell
$env:BOT_DEEPSEEK_KEY = 'your-key'
python tools/ai_community_bot.py --agents 300 --concurrent 60
```

账号画像和行为状态保存在 `tools/bot_state.json`；手机号和 JWT 单独保存在已忽略的 `tools/bot_credentials.json`。轮换所有机器人令牌但不启动模拟器：

```powershell
python tools/ai_community_bot.py --rotate-tokens-only
```

后端使用无状态 JWT，重新签发不会立即吊销旧令牌；旧令牌会在 `BOWALL_JWT_EXPIRES_HOURS` 配置的时间后过期。模拟器默认按真实经过时间上报帖子停留；仅在本地快速测试时可通过 `BOT_DWELL_TIME_SCALE` 缩短等待。

头像只使用生成式图像源。外部照片帖子默认关闭；只有在已确认图片使用与署名条件时，才应设置 `BOT_ENABLE_EXTERNAL_POST_IMAGES=true`。

前端文件位于 `src/main/resources/static/`，修改后执行 `mvn resources:resources` 同步到运行目录即可，无需重启后端。

## 接口分组

| 分组 | 根路径 |
| --- | --- |
| 用户、关注、粉丝 | `/user`、`/followers`、`/fans` |
| 内容、评论、点赞、图片 | `/posts`、`/comments`、`/like`、`/image` |
| 消息与通知 | `/message`、`/notification` |
| 二维码与实时通信 | `/qrcode`、`/websocket` |

具体参数与返回值以各 Controller 的注解和 Swagger UI 页面为准。

## 注意事项

- 命令行执行 `mvn compile` 时，JDK 26 与 Lombok 组合可能报 `Cannot close compiler resources`，但 class 文件已正常生成，IDEA 直接运行不受影响。
- `application-local.yml`、`uploads/`、`.m2/` 均已加入 `.gitignore`，请勿提交本机密码与图片。
- `src/test` 中部分测试会连接真实数据库或本机图片路径，默认不应直接运行。
