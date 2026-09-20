# 贝尔格莱德租房项目 — 稳定状态说明

> 最后固化：2026-09-20（git commit `a334f2c`）。在此之上迭代时，请先读本文件 + `AGENTS.md`。

## 1. 项目结构

| 文件 | 作用 |
|---|---|
| `scraper.py` | 主爬虫：3 源抓取（CityExpert / HaloOglasi / 4zida）+ 过滤 + 渲染看板 + 详情页 + 微信推送 |
| `send_wechat.py` | 独立微信 CLI 推送（`push_all` / `push`），统一通道+超时+重试 |
| `card_render.py` | 微信图文卡片生成器（`data/card.html` / `card.png` / `card_text.md`） |
| `friend_push_template.html` | 好友推送模板 |
| `serve/guardian.sh` | 常驻守护：静态服务 + cloudflared 隧道 |
| `serve/serve_static.sh` / `tunnel_static.sh` | 静态服务与隧道启动脚本 |

## 2. 关键配置（硬编码常量，无独立 config.json）

`scraper.py` 顶部：
- `MIN_PRICE = 350` / `MAX_PRICE = 650` — 价格区间
- `OUTPUT_BASE`：优先外接盘 `/Volumes/Data2TB/rent`，不可写则回退本地 `BASE_DIR/output`
- `TODAY_OUTPUT_DIR = OUTPUT_BASE/output_<日期>/`，详情页在 `details/` 子目录

`send_wechat.py`：
- 微信 target `o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat`（用户 sgy9313）
- 通道 `openclaw-weixin`，120s 超时，3 轮重试/5s 退避

## 3. 运行方式

```bash
# 完整跑（抓取 + 渲染 + 推送微信）
/Users/SGY/BelgradeRentals/.venv/bin/python /Users/SGY/BelgradeRentals/scraper.py
```

- **不要**用 `source .venv/bin/activate`（该 venv 的 pip 已损坏，报 No module named cloudscraper）。
- 每日 02:00 定时抓取，任务 id `aeb1c617-4652-4e80-b820-177469b70816`。
- 新增判定信号读 `data/push_pending.json`。

## 4. 三源解析要点（已修复的坑，勿回退）

### HaloOglasi
- **价格**：必须按 `.product-item` 卡片隔离解析。用 `page.query_selector_all('.product-item')` 逐卡，取卡内 `span[data-value]`（兜底 `.central-feature i`），经 `halo_card_price()` → `parse_price()` → `within_budget()`。
  - ⚠️ 严禁用全局跨标签正则 `data-id...data-value`，会把相邻卡片价格串错。
- **图片**：取卡片内 `img[src*=slike][src*=oglasi]` 真实图（`halo_card_image()`，归一化 `//`）；卡片无大图时访问详情页取 `og:image`。
  - ⚠️ 列表页 DOM 只有广告(adocean.pl)+Handlebars 模板占位(`{{...}}`)+`no-image.jpg`，直接截列表页必得占位/广告图。
- **链接**：卡片内 `.product-title a[href]` 或 `.a-images[href]`。

### CityExpert（Angular ng-state JSON）
- 拦截 `api/search` 响应取 `result` 列表；图片用 `https://img.cityexpert.rs/properties/470x/<path>`。

### 4zida
- 正则 `href...(\d+)\s*€`；`parse_price`清洗。

## 5. URL 路径铁律（404 教训）

- **静态服务根目录 = OUTPUT_BASE（`/Volumes/Data2TB/rent`）**，不是今日输出目录。
- 所以所有外链必须带 `output_<日期>/` 前缀：
  - 看板：`{public_url}/output_<日期>/index_<日期>.html`
  - 详情页：`{public_url}/output_<日期>/details/house_N.html`
- 推微信前应自检：`urllib.request.urlopen(链接)` 返回 HTTP 200。
- Cloudflare 隧道为该 `rent` 目录（`--url http://127.0.0.1:8765`），root 即外接盘 `rent`，无边缘缓存（`cf-cache-status: DYNAMIC`）。

## 6. 端口 8765 冲突（勿重蹈）

- guardian 常驻服务**已占用** `127.0.0.1:8765`（root = `/Volumes/Data2TB/rent`），且有 live 公网 URL（`logs/guardian_state.json`）。
- 完整跑 `main()` 时 `start_local_server_and_tunnel` 会在 8765 起新服务 → 端口冲突报 `OSError: Errno 48`，导致推送被跳过。
- **正确做法**：复用 guardian 已有 public_url（读 `logs/guardian_state.json` / `logs/tunnel_url.txt`），直接调 `push_all` 推送，不要自己再起隧道。

## 7. 看板样式要点

- 标头：`BELGRADE RENTALS`（原 `Belgrade · Chinese Edition`）。
- 标题不含 `#房源ID`（该编号 = 网站原生 Listing ID，与 URL 尾部一致，无展示价值，已从 title 移除；去重仍用 `id` 字段）。
- `card_render.py` 的微信图文卡显示 street，不含 #编号。

## 8. 微信推送格式

- 纯文本列表：`序号. [来源] 价格€ - 标题` + 详情页链接 + 看板链接。
- 有新增才推详情；无新增推"暂无新增"静默模板。走 `push_all` 稳定链路。
