# 接入 DeepSeek

## 先确认一件事

"OpenAI 兼容"是**接口格式**，不是"要用 OpenAI 这家公司"。DeepSeek、智谱、阿里百炼、
月之暗面都实现了同一个协议：

    POST {base_url}/chat/completions
    Authorization: Bearer <你的 key>
    {"model": "...", "messages": [{"role": "user", "content": "..."}]}

所以项目里叫 LLM_BASE_URL，填哪家都行。你没有 OpenAI 账号也能跑。

---

## 三分钟接上

**第一步，拿 key。** 打开 https://platform.deepseek.com ，注册，充值（最低 10 元），
在「API keys」里创建一个，形如 sk-xxxxxxxx。**只显示一次，当场复制保存。**

**第二步，建 .env。** 在项目根目录（和 run.py 同一层）新建文件 .env，写三行：

    LLM_BASE_URL=https://api.deepseek.com/v1
    LLM_API_KEY=sk-你复制的那串
    LLM_MODEL=deepseek-chat

注意 base_url 末尾的 /v1。写成 api.deepseek.com 也能通，但加上 /v1 最稳。

**第三步，自检。**

    python tools\check_llm.py

看到 [OK] 文本 就通了。此时 python run.py 右上角会显示「已接入模型」。

---

## 视觉怎么办

**DeepSeek 没有视觉模型。** 你们的「拍照 → 出 listing」这一环会缺少视觉识别。
两种处理：

### 方案一：降级（一分钱不花）

VISION_MODEL 留空。上传照片时，程序会明确告诉你「这边没有接视觉模型」，
然后按预置品类往下走，你在对话里打一行字纠正即可。

答辩时这样可以讲成"多模态可选、成本可控"，但 Demo 的视觉冲击力会弱一截。

### 方案二：文本 DeepSeek + 视觉智谱（推荐）

智谱的 glm-4v-flash 有免费档，注册 https://open.bigmodel.cn 就能拿到 key。
两家模型可以并存，.env 写成：

    LLM_BASE_URL=https://api.deepseek.com/v1
    LLM_API_KEY=sk-deepseek的key
    LLM_MODEL=deepseek-chat

    VISION_BASE_URL=https://open.bigmodel.cn/api/paas/v4
    VISION_API_KEY=智谱的key
    VISION_MODEL=glm-4v-flash

文本走 DeepSeek（便宜、中文好），识图走智谱（免费）。代码里这两条链路是分开的，
互不影响。

---

## 模型怎么选

用 deepseek-chat，不要用 deepseek-reasoner。

原因：这个项目的关键节点要模型返回**严格 JSON**（response_format=json_object），
reasoner 是推理模型，对 temperature 和 JSON 模式的支持不一样，容易返回一段带思考过程的
文本，解析会失败。deepseek-chat 足够。

---

## 成本

DeepSeek 按 token 计费，价格很低，10 元够你们把三个案例反复跑上百遍。真实数字以
官方价目页为准——答辩时用 GET /api/usage 拿到实测值再换算，别引用别人的数。

---

## 顺便：JoyCode 编辑器也能用这个 key

JoyCode 设置 → 模型 → 添加自定义模型 → API 提供商选 DeepSeek → 粘贴同一个 key →
模型选 deepseek-chat → 确认。这样编辑器里写代码也有模型可用了。

注意：这一步只是让 JoyCode 助手有模型，**不会**让你的 Python 程序自动获得接口。
程序能不能调模型，只看 .env 那三行。
