# BoWall Java 后端

BoWall 是配套微信小程序的社交内容后端，基于 Spring Boot、MyBatis-Plus、MySQL、Redis 与 WebSocket。

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
```

资源目录中的 `mapper/` 存放 XML 映射文件；`src/test` 中部分测试会连接真实数据库或本机图片路径，默认不应直接运行。

## 本地启动

要求：JDK 26、Maven 3.9+、MySQL 及 Redis。

在 PowerShell 中配置运行所需的环境变量：

```powershell
$env:BOWALL_DB_URL = 'jdbc:mysql://127.0.0.1:3306/bowall?serverTimezone=Asia/Shanghai&useUnicode=true&characterEncoding=utf-8&zeroDateTimeBehavior=convertToNull&useSSL=false&allowPublicKeyRetrieval=true'
$env:BOWALL_DB_USERNAME = 'root'
$env:BOWALL_DB_PASSWORD = 'your-password'
$env:BOWALL_REDIS_HOST = '127.0.0.1'
$env:BOWALL_REDIS_PORT = '6379'
$env:BOWALL_REDIS_PASSWORD = 'your-password'
```

然后执行：

```powershell
mvn spring-boot:run
```

构建（不执行会访问外部依赖的历史测试）：

```powershell
mvn -DskipTests package
```

配置字段说明与可复制的变量模板见 `src/main/resources/application-example.yml`。本地私有配置可放在 `application-local.yml`，该文件已被 Git 忽略。

## 主要接口分组

| 分组 | 根路径 |
| --- | --- |
| 用户、关注、粉丝 | `/user`、`/followers`、`/fans` |
| 内容、评论、点赞、图片 | `/posts`、`/comments`、`/like`、`/image` |
| 消息与通知 | `/message`、`/notification` |
| 二维码与实时通信 | `/qrcode`、`/websocket` |

具体参数与返回值以各 Controller 的注解和 Swagger/Knife4j 页面为准。
