# 小组成员本地配置：只映射变量名

每位成员在自己的电脑运行后端。代码共用，密钥和模型配置留在本机；不需要改七个模块。项目不能自动知道任意自定义变量代表哪个服务，也不能让没有密钥的电脑凭空调用你的账号，所以首次仍需填写一次对应关系。

## 百炼：文本、搜索、生图共用本机账号

假设成员原有环境变量名是 `DASHSCOPE_API_KEY`（密钥）和 `MY_QWEN_URL`（该密钥对应的接口地址）。项目根目录创建 `.env`：

```dotenv
LLM_PROVIDER=bailian
BAILIAN_API_KEY_ENV=DASHSCOPE_API_KEY
BAILIAN_BASE_URL_ENV=MY_QWEN_URL
BAILIAN_TEXT_MODEL=qwen-plus
BAILIAN_IMAGE_MODEL=qwen-image-2.0
M1_MODE=live
M2_MODE=live
M3_MODE=live
M4_MODE=live
HUB_DATA_DIR=data/group02
LLM_TIMEOUT_SECONDS=120
```

`BAILIAN_API_KEY_ENV=DASHSCOPE_API_KEY` 的意思是“从本机 DASHSCOPE_API_KEY 读取密钥”，右侧不是密钥内容。如果另一个人用 `ALI_TOKEN`，只把右侧改成 `ALI_TOKEN`。地址、模型名也可这样映射；没有对应环境变量时，直接写非敏感的地址/模型值即可。

仓库 [.env.team.example](../.env.team.example) 提供可复制模板，里面的占位变量名必须修改。已有 `.env` 时只合并需要的行，不覆盖已有设置。本机标准 `BAILIAN_*` 配置继续有效，无需迁移。

## 其他文本模型服务

用支持现有 Chat Completions 协议及 Planner JSON 输出模式的服务。例如成员原有 `COMPANY_TOKEN`、`COMPANY_MODEL_URL`、`COMPANY_MODEL_NAME`：

```dotenv
LLM_API_KEY_ENV=COMPANY_TOKEN
LLM_BASE_URL_ENV=COMPANY_MODEL_URL
LLM_MODEL_ENV=COMPANY_MODEL_NAME
HUB_DATA_DIR=data/group02
```

同样可以直接设置 `LLM_MODEL=实际模型名`，不必为了非敏感配置再建环境变量。**文本协议兼容不等于搜索、生图也兼容**。可单独映射：

```dotenv
# 示例：独立的百炼搜索服务
M4_SEARCH_PROVIDER=bailian
M4_SEARCH_API_KEY_ENV=MY_SEARCH_TOKEN
M4_SEARCH_URL_ENV=MY_SEARCH_ENDPOINT
M4_SEARCH_MODEL=qwen-plus

# 示例：独立的百炼图片服务
M4_IMAGE_PROVIDER=bailian
M4_IMAGE_API_KEY_ENV=MY_IMAGE_TOKEN
M4_IMAGE_BASE_URL_ENV=MY_IMAGE_ENDPOINT
M4_IMAGE_MODEL=qwen-image-2.0
```

搜索现有协议为 bailian/tavily，图片为 bailian/openai兼容；变量名映射不会把不兼容的服务变成兼容服务。模型、地域/业务空间、权限和余额仍由各人的账号决定。

## 检查与启动

在已安装项目依赖的后端环境运行（Windows示例）：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_live_config
```

输出仅显示配置来源、缺少的标准字段、哪些字段使用映射；不打印密钥、地址或变量值，也不联网、不收费。

- `configured: true` 只表示该服务必需字段齐全，不证明密钥有效或服务可访问。
- `mapped_settings` 列出已启用映射的标准字段。
- 退出码0：全部服务字段齐全；1：存在缺配置的服务；2：变量映射/配置错误。文本配置齐全但搜索或生图未配时，文本功能仍可用，不能据此称四类服务全就绪。
- 提示 `*_ENV points to an unset or empty environment variable`：检查右侧变量名，并重新打开终端，让新设置的系统/用户环境变量进入当前进程。项目不自动读取其他终端的临时变量。

随后按 [前端接入说明](frontend_handoff.md) 使用 `python -m web` 启动本机后端及页面，默认真实 Planner 与七个真实模块。前端只连接本机后端；不要把模型密钥放入前端可打包的环境变量。没有服务配置时可显式使用 `--offline` 排练；不会自动降级为 Mock。

## 明确的优先级

1. 系统/进程环境优先于 `.env` 中同名配置（dotenv不覆盖已有值）。
2. 有效的 `字段_ENV` 映射优先于该字段原有直接值。映射源不存在时直接报错，不改用旧值或其他账号。
3. 无映射时保持原逻辑：任一非空 `LLM_BASE_URL/API_KEY/MODEL` 选中整组 `LLM_*`；不会从百炼/DeepSeek补借缺失字段。否则由 `LLM_PROVIDER` 选择服务。
4. 搜索/图片显式覆盖也按整组选择；配置百炼共用组时，避免残留不完整的 `M4_SEARCH_*`/`M4_IMAGE_*`。
5. 映射只读取一次原始变量值，不支持递归别名，也不修改系统环境。

支持在以下字段后加 `_ENV`：`LLM_PROVIDER`、`LLM_BASE_URL/API_KEY/MODEL`、`DEEPSEEK_BASE_URL/API_KEY/MODEL`、`BAILIAN_BASE_URL/API_KEY/TEXT_MODEL/SEARCH_MODEL/IMAGE_MODEL`、`M4_SEARCH_PROVIDER/URL/API_KEY/MODEL`、`M4_IMAGE_PROVIDER/BASE_URL/API_KEY/MODEL`、`HUB_PLANNER_MODEL`。这里斜线表示各个完整字段名，不是实际变量名。

`.env` 已忽略追踪。可分享不含密钥的映射示例；任何机器都不需要把自己的密钥提交到仓库。

## 本次验证（2026-10-15）

全量离线1376项通过、34项跳过（31项真实API默认关闭，3项安装包测试随后单独补跑并全部通过）；安装后7项独立运行检查通过。新增11项映射测试覆盖整组优先级、缺失变量拒绝回退、文本/搜索/生图/Planner、单层解析、环境不变及错误脱敏。

另用本机百炼配置在临时子进程改名，实际运行配置检查：四类服务字段齐全；源变量不存在时退出码2。没有改系统环境或本机 `.env`，没有联网或调用收费服务；这次验证不代表其他成员的密钥或模型已经实测。
