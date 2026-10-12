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

# 已中断任务可接续执行；使用 --force 忽略阶段进度重新分析
xuanping analyze --category 283155 --task <task-id> --resume
xuanping analyze --category 283155 --task <task-id> --force

# 3. 导出 Markdown 报告（将 <task-id> 替换为分析任务 ID）
xuanping report --task <task-id> --format md --output report.md
```

榜单类型支持 `bestsellers`、`movers`、`new`。也可以先 collect，再用 `xuanping analyze --category 283155 --task <collect-task-id>` 接续榜单采集结果。数据库默认保存在 `xuanping.db`，可通过 `XUANPING_DATABASE_PATH` 修改。

分析阶段会逐商品持久化采集、详情、打分和差评进度；默认续跑已完成步骤，`--force` 会重新执行。Google Trends 只查询打分 Top N（`XUANPING_TRENDS_TOP_N`），每次最多批量查询 5 个关键词。

## 1688 供应链比价与代理

配置 LLM API Key 后，默认启用 1688 比价：Agent 将英文商品标题提炼为中文搜索词，对候选供应商商品进行语义匹配，并在报告中列出价格区间、MOQ、相似度和估算毛利。只有匹配置信度足够时才使用该成本；否则回退到 `XUANPING_DEFAULT_COST_MULTIPLIER`。可用 `XUANPING_ENABLE_1688=false` 关闭，`XUANPING_CNY_USD_RATE` 默认 7.2，需定期更新。

成本可信度在评分明细的 `cost_source` 中标记：
- `1688_high`：2–3 个有效报价，相似度均 ≥80，价格离散度 ≤30%。
- `1688_medium`：单个有效报价且相似度 ≥85，或多个有效报价相似度均 ≥65、价格离散度 ≤50%。成本可用，但仍需人工确认规格、MOQ、运费和供应商可靠性。
- `fallback`：未获得可用报价、相似度不足或报价差异过大，使用默认成本倍率估算。

价格离散度为（最高报价上限 − 最低报价下限）/ 报价中点均值；单个报价的离散度为不适用（JSON 中为 `null`），不能视为多供应商交叉验证。

### 1688 静态采集现状与排查

当前只实现静态 HTTP 采集，**搜索 URL 和选择器未经真实页面验证，不保证抓通**。1688 搜索通常依赖 JavaScript 和登录态；HTTP 200 也可能只返回空壳、登录页或验证页。空报价不等于没有供应商，采集失败时成本会回退，不应据此作采购决策。

- `XUANPING_1688_SEARCH_URL` 可替换为获准使用的搜索页模板，必须包含 `{keywords}`，默认仍为旧版搜索 URL。
- `XUANPING_1688_KEYWORD_ENCODING=utf-8|gbk` 控制关键词编码，默认 `utf-8`。仅在目标页面确实需要时选择 `gbk`；无法编码的字符会报错并由 pipeline 记录，不会悄悄丢弃字符。
- 0 条报价时，中文告警记录 HTML 长度、候选节点数，并区分页面明确无商品、疑似登录/反爬拦截、选择器失效或 JS 未渲染；这些是启发式诊断，不是真实页面可用性的证明。没有任何商品线索的静态页面也会提示不能认定真实搜索无结果。
- 排查时先查看日志，再在有权限的浏览器中手动确认搜索结果、编码和页面结构；有商品但抓不到时，核对 `collectors/supplier_1688.py` 中集中管理的选择器。遇到验证码或 HTTP 401/403/429，不自动重试或绕过限制。
- 本轮未内置自动 Playwright 后备流程，也未实现 `XUANPING_1688_USE_BROWSER` 开关。需要动态页面时，可安装已有 `browser` extra（`pip install -e ".[browser]"`，并运行 `playwright install chromium`），在获准访问的环境中实现并注入浏览器版 supplier collector，复用 `collect(keywords, limit)` 接口。浏览器不是绕过登录、验证码或平台授权的工具。

代理通过 `XUANPING_PROXIES` 配置，支持 `XUANPING_PROXY_STRATEGY=random|round_robin`、失败剔除与冷却。启动健康检查默认关闭。Amazon/1688 采集均采用保守延迟，并在检测到 CAPTCHA 时立即中止；代理不能用于规避访问控制。

FBA 费用按包装尺寸和重量段估算，缺失时采用保守回退；费率表是简化近似值，使用前须核对 Amazon Seller Central 官方费率和类目佣金。

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

Markdown 和 CSV 中的维度 `N/A` 表示数据缺失、无法给出有效评分，不是 0 分或满分；JSON 中对应为 `null`。总分只对有数据且权重为正的维度动态归一化，因此必须结合数据完整度审阅。品牌占比只以本次实际参与评分的商品（含未知品牌）为分母，是同一榜单内品牌集中度的代理指标，并非市场份额；纯采集阶段不计算该指标。

## 模块

- `config.py`：`.env` 配置、provider 切换和默认值。
- `llm/`：OpenAI 兼容客户端、指数退避重试、JSON 解析和痛点提示词。
- `collectors/`：Amazon 榜单、商品、低星评论以及 Google Trends 采集；HTTP 客户端可注入 mock。
- `analysis/bsr_sales.py`：类目 BSR 幂律销量估算、置信区间和 SQLite 自校准。初始曲线是经验估计，不能替代历史销量数据。
- `analysis/scoring.py`：需求、竞争、利润、机会、风险五维打分，并返回各维明细。
- `analysis/fba_fees.py`：按尺寸重量估算 FBA 履约费和类目佣金；`analysis/sourcing.py`：LLM 语义匹配 1688 供应链。
- `collectors/proxy_pool.py`：代理轮换、连续失败剔除和冷却恢复。
- 默认评分权重可通过 `.env` 中 `XUANPING_SCORE_WEIGHTS` 的 JSON 对象调整；成本倍率可通过 `XUANPING_DEFAULT_COST_MULTIPLIER` 调整。
- `pipeline.py`：分步容错编排、SQLite 中间结果与 Markdown/CSV/JSON 报告。
- `cli.py`：`collect`、`analyze`、`report`、`calibrate` 命令。

FBA 费用、佣金、广告及成本均采用简化估算；评分权重和成本倍率应根据具体站点、类目和业务数据复核。采集与 LLM 客户端均可传入 mock 对象，测试不访问真实网络。

## 合规与风险声明

抓取 Amazon 或 1688 页面可能违反相应平台服务条款或触发访问限制；1688 页面和商品数据采集亦须先确认平台许可、适用法律及数据使用权。本项目仅供学习研究，使用者须自行承担风险。请控制访问频率；配置代理仅是网络配置，不代表获得授权或规避平台限制。检测到 CAPTCHA 后程序会中止，禁止将本项目用于绕过验证码、访问控制或收集非公开信息。
