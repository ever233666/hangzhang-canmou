# 部署说明（Sealos / 任意容器）

只用 Python 标准库跑网页和调模型；导出 PDF / Word 需要 Pillow 与 python-docx
（本地用 `pip install pillow python-docx`，本仓库自带的 Dockerfile 会在构建时装好）。

容器镜像基于 `python:3.11-slim`，**中文 PDF 依赖系统 CJK 字体**，Dockerfile 里已装
`fonts-noto-cjk`。自己写 Dockerfile 时漏了这一步，导出的 PDF 会是方块或直接 500。

## 一、环境变量（必须对）

| 变量 | 值 | 说明 |
|---|---|---|
| `PORT` | 平台注入，或 8000 | 必须与应用端口一致 |
| `HOST` | `0.0.0.0` | 容器里绑回环地址，网关连不进来 |
| `LLM_BASE_URL` | 如 `https://open.bigmodel.cn/api/paas/v4` | OpenAI 兼容端点 |
| `LLM_API_KEY` | 你的密钥 | 缺失会自动退回样例模式 |
| `LLM_MODEL` | 如 `glm-4-plus` | |
| `VISION_BASE_URL` | 可选 | 不填则拍照链路降级为文字 |
| `VISION_API_KEY` | 可选 | |
| `VISION_MODEL` | 可选，如 `glm-4v-flash` | |
| `REQUIRE_PASSWORD` | `0`（默认关） | 想加口令才设为 `1` |
| `ACCESS_USER` | 如 `judge` | 评审账号（仅加锁时用） |
| `ACCESS_PASSWORD` | 自己定，别太短 | **只写这个不生效**，必须同时 `REQUIRE_PASSWORD=1`；留空=打开即用 |
| `RATE_LIMIT` | `120` | 每个 IP 每小时能发多少条对话，防止公开链接被刷额度；`0` 关闭 |
| `AUTO_REFRESH` | `0` | 容器里关掉启动扫描，避免冷启动慢 |
| `TZ` | `Asia/Shanghai` | 不设则用 UTC，报价单日期会差一天（代码已兜底，可留空） |

## 二、部署后必查四件事

1. `https://你的域名/api/health` 返回 `{"ok":true,"mock":false,"auth":true}`。
   - `mock:true` = 没读到密钥，评委看到的是样例数据，**必须修**。
   - `auth:false` = 没设 ACCESS_PASSWORD，谁拿到链接都能用你的额度。
2. 打开首页应跳到 `/login`，输口令后进入工作台。
3. 发一句「我做碳纤维自行车车架，想卖到欧盟」，确认能连续追问、能出 listing。
4. 导出一次报价单 PDF，确认容器里能生成中文 PDF（字体走 PIL 内置，不依赖系统字体）。

## 三、Sealos 上的两个坑

- **端口**：App Launchpad 里配置的容器端口必须等于 `PORT`，否则 502。
- **副本数**：缩到 0 的免费规格会冷启动，评委第一下可能要等十几秒。录制演示前先访问一次预热。

## 四、数据

会话与档案写在 `data/`，容器重启即丢。这是刻意设计：每位访客一个独立会话，不把上一位的信息留给下一位。若需要留存，把 `data/` 挂成持久卷，但注意 `data/byok.json` 里是密钥。
