# xuanping — 亚马逊选品 Agent

面向亚马逊卖家的选品分析 CLI：使用 Amazon 公开榜单与商品页、Google Trends 免费数据、可校准的 BSR 销量经验估算，以及智谱 GLM / 阿里 Qwen 进行差评痛点归纳。**不依赖 Keepa、Helium 10 等付费数据 API。**

> 销量、费用、趋势和评分均为估算，不构成经营或投资建议。Amazon 页面结构及可访问性可能变化。

## 安装

需要 Python 3.11 或更高版本：

```bash
git clone https://github.com/jaren-cmi/xuanping.git
cd xuanping
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

需要可选浏览器依赖时安装 `pip install -e ".[browser]"`；此 extra 只提供 Playwright，本项目默认使用轻量 HTTP 采集。

## 配置智谱或 Qwen

```bash
cp .env.example .env
```

编辑 `.env`，设置 `XUANPING_LLM_PROVIDER` 为 `zhipu` 或 `qwen`，并填入对应 `XUANPING_LLM_API_KEY`。默认模型分别为 `glm-4-flash`、`qwen-plus`；可通过 `XUANPING_LLM_MODEL` 和 `XUANPING_LLM_BASE_URL` 覆盖。智谱默认地址为 `https://open.bigmodel.cn/api/paas/v4/`，DashScope 默认地址为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。

## 跑通一次完整流程

```bash
# 1. 采集榜单（Amazon 页面请求之间默认随机间隔 2–5 秒）
xuanping collect --category 283155 --type bestsellers

# 2. 对类目运行完整分析；记下输出的任务 ID
xuanping analyze --category 283155 --top 20

# 3. 导出 Markdown 报告（将 <task-id> 替换为分析任务 ID）
xuanping report --task <task-id> --format md --output report.md
```

榜单类型支持 `bestsellers`、`movers`、`new`。也可以先 collect，再用 `xuanping analyze --category 283155 --task <collect-task-id>` 接续榜单采集结果。数据库默认保存在 `xuanping.db`，可通过 `XUANPING_DATABASE_PATH` 修改。

使用已知真实销量样本校准类别曲线，CSV 必需包含 `bsr,monthly_sales` 两列，可选 `category` 列：

```csv
category,bsr,monthly_sales
home,100,600
home,500,180
home,1000,100
```

```bash
xuanping calibrate --file samples.csv
```

支持 `xuanping report --task <task-id> --format md|csv|json`。

## 模块

- `config.py`：`.env` 配置、provider 切换和默认值。
- `llm/`：OpenAI 兼容客户端、指数退避重试、JSON 解析和痛点提示词。
- `collectors/`：Amazon 榜单、商品、低星评论以及 Google Trends 采集；HTTP 客户端可注入 mock。
- `analysis/bsr_sales.py`：类目 BSR 幂律销量估算、置信区间和 SQLite 自校准。初始曲线是经验估计，不能替代历史销量数据。
- `analysis/scoring.py`：需求、竞争、利润、机会、风险五维打分，并返回各维明细。
- 默认评分权重可通过 `.env` 中 `XUANPING_SCORE_WEIGHTS` 的 JSON 对象调整；成本倍率可通过 `XUANPING_DEFAULT_COST_MULTIPLIER` 调整。
- `pipeline.py`：分步容错编排、SQLite 中间结果与 Markdown/CSV/JSON 报告。
- `cli.py`：`collect`、`analyze`、`report`、`calibrate` 命令。

FBA 费用、佣金、广告及成本均采用简化估算；评分权重和成本倍率应根据具体站点、类目和业务数据复核。采集与 LLM 客户端均可传入 mock 对象，测试不访问真实网络。

## 合规与风险声明

抓取 Amazon 页面可能违反 Amazon 服务条款或触发访问限制；本项目仅供学习研究，使用者须自行确认适用法律、平台条款和数据使用许可，并自行承担风险。请控制访问频率；配置代理仅是网络配置，不代表获得授权或规避平台限制。避免使用与卖家账号相同的 IP 进行实验，优先使用平台许可的官方数据接口。不得将本项目用于绕过验证码、访问控制或收集非公开信息。
