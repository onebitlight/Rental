# 贝尔格莱德租房项目 — 稳定状态说明

> 最后固化：2026-10-11（HaloOglasi 动态渲染字段修复 + CityExpert 图片 CDN 分桶规则固化）。在此之上迭代时，请先读本文件 + `AGENTS.md` + `DEVELOPER_NOTES.md`。
> 技术陷阱和架构决策沉淀见 `DEVELOPER_NOTES.md`——遇到 404、面积缺失、房间数异常等已知问题时优先查阅。

## 0. 版本存档

| 固化时间 | commit | 说明 |
|---|---|---|
| 2026-09-19 | `a334f2c` | 固化稳定状态：修复 HaloOglasi 解析 + 看板链接路径 + 推送链路 |
| 2026-09-20 | `7b287a4` | 添加 PROJECT_NOTES.md：记录稳定配置/运行逻辑/路径铁律 |
| 2026-09-20 | `c79c669` | **重构房源卡片渲染逻辑**：真实塞语片区+中文翻译标题、动态核心参数副标题（面积·几房·供暖·车位/家具）、`--rerender` 回放模式 |
| 2026-09-27 | `494aeb7` | `run_all.sh` 增加 `ENABLE_STAN`/`ENABLE_KUCA` 开关与 `stan`/`kuca` 模式传参 |
| 2026-09-27 | `aa122f0` | **抓取策略固化**：Stan 预算 €350-650 多页翻页；Kuca 预算 €500-1300 深度翻页 + 关闭强制视觉筛选，实测各成功 |
| 2026-10-01 | — | **路径规范化固化**：公寓爬虫统一为 `scraper_stan.py`、公寓去重历史库统一为 `data/history_stan.json` |
| 2026-10-02 | — | **产出路径彻底重构**：`card_render.py` + `scraper_stan.py` + 静态服务器 + 守护脚本 全部统一至 `/Volumes/Data2TB/ai_output/BelgradeEstate/`，旧 `/Volumes/Data2TB/rent/` 废弃 |

## 0. 版本存档（续）

| 固化时间 | commit | 说明 |
|---|---|---|
| 2026-10-10 | — | **静态服务目录 + 守护防冲突铁律固化**：Python 3.9 `--directory` 参数不可靠，统一用 `os.chdir()` 内联方案；`keep_static_alive.sh` 替代旧 `keep_tunnel_alive.sh`；Tunnel 完全由 LaunchDaemon 接管 |
| 2026-10-09 | — | **微信推送最终固化**：`send_wechat.py` 定为唯一推送标准实现，单条汇总格式 + `push_daily_summary()` 统一入口，同步更新 MEMORY.md + PROJECT_NOTES.md |

## 1. 多业态开关铁律（2026-09-28 固化）

- **所有爬虫脚本（含未来的写字楼、商铺脚本）顶部必须定义 `ENABLE_<TYPE>_SCRAPER` 开关**，例如：
  - `scraper_stan.py` → `ENABLE_STAN_SCRAPER`
  - `scraper_kuca.py` → `ENABLE_KUCA_SCRAPER`
  - 未来写字楼 → `ENABLE_OFFICE_SCRAPER`、商铺 → `ENABLE_SHOP_SCRAPER`（类型命名保持一致）。
- **入口 `if __name__ == "__main__":` 必须判断开关**；开关为 `False` 时应置空该业态数据文件（`stan_temp.json` / `kuca_temp.json`）并直接退出，不抓取、不渲染、不推送。
- **当前 `ENABLE_STAN_SCRAPER = True`（公寓启用中，2026-09-29 用户明确指示长期开启）**；如要暂停公寓抓取，仅在用户本人明确指示后才能关闭。
- `ENABLE_KUCA_SCRAPER = True`（独栋启用中）。
- `run_all.sh` 无参模式读取这些开关决定是否执行对应抓取；`stan`/`kuca` 传参强制单跑对应类型（绕过开关）。

## 2. 项目结构

| 文件 | 作用 |
|---|---|
| `run_all.sh` | **统一入口**（2026-09-27 起取代 scraper.py）：依次跑 `scraper_stan.py`→`card_render.py stan`；`scraper_kuca.py`→`card_render.py kuca` |
| `scraper_stan.py` | **公寓(Stan)抓取（唯一规范命名）**：CityExpert / HaloOglasi 等源 + 过滤 + 去重（写 `data/history_stan.json`）+ 写 `data/stan_temp.json` |
| `scraper_kuca.py` | 独栋(Kuca)抓取 + 过滤 + 去重（写 `data/history_kuca.json`）+ 写 `data/kuca_temp.json` |
| `card_render.py` | 看板卡片渲染（`<stan|kuca>_<日期>/index_<日期>.html`）；微信图文卡（`data/card.html`/`card.png`/`card_text.md`） |
| `send_wechat.py` | **微信推送唯一标准实现**：`push_daily_summary()` 统一汇总入口（公寓+独栋单条推送），含价格区间自动计算、预设回退、CLI argparse 兼容层 |
| `card_render.py` | 微信图文卡片生成器（`data/card.html` / `card.png` / `card_text.md`） |
| `friend_push_template.html` | 好友推送模板 |
| `serve/guardian.sh` | 常驻守护：静态服务 + cloudflared 隧道 |
| `serve/serve_static.sh` / `tunnel_static.sh` | 静态服务与隧道启动脚本 |

## 3. 关键配置（硬编码常量，无独立 config.json）

**预算与抓取参数（2026-09-27 固化，commit `aa122f0`，实测成功）**：
- `scraper_stan.py`（公寓）：`MIN_PRICE=350` / `MAX_PRICE=650`，`MAX_PAGES=3` 多页翻页（CityExpert + HaloOglasi 均带预算参数）
- `scraper_kuca.py`（独栋）：`MIN_PRICE=500` / `MAX_PRICE=1300`，`MAX_PAGES=3` 深度翻页（可抓取远郊/性价比房源），`ENABLE_VISION_FILTER=False`（关闭强制视觉识别筛选，避免误过滤；改 `True` 才开启严格图片筛选）

**所有抓取/渲染脚本顶部通用**：
- `OUTPUT_BASE`：优先外接盘 `/Volumes/Data2TB/ai_output/BelgradeEstate`，不可写则回退本地 `BASE_DIR/output`
- **看板路径已改为按类型分目录**：`/Volumes/Data2TB/ai_output/BelgradeEstate/stan_<日期>/index_<日期>.html`（公寓）、`/Volumes/Data2TB/ai_output/BelgradeEstate/kuca_<日期>/index_<日期>.html`（独栋）
- 详情页在各自 `details/` 子目录

`send_wechat.py`：
- 微信 target `o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat`（用户 sgy9313）
- 通道 `openclaw-weixin`，120s 超时，3 轮重试/5s 退避

## 4. 运行方式

```bash
# 统一入口（抓取 + 渲染看板，公寓+独栋）
bash ~/Projects/BelgradeEstate/run_all.sh
# 仅公寓
bash ~/Projects/BelgradeEstate/run_all.sh stan
# 仅独栋/别墅
bash ~/Projects/BelgradeEstate/run_all.sh kuca
```

- **运行模式控制**（run_all.sh 内部）：
  - 默认（无参数）读取脚本内 `ENABLE_STAN` / `ENABLE_KUCA` 两个全局开关（改 `false` 即关闭对应抓取）。
  - 传参 `stan` / `kuca` 强制只跑对应类型；传参时即使对应开关为 `false` 也会强跑（`|| [ "$MODE" = "stan/kuca" ]`）。
  - 定时调用的主命令保持 `bash ~/Projects/BelgradeEstate/run_all.sh`（读开关配置）。
- ⚠️ **旧的 `scraper.py` 已于 2026-09-27 彻底移除**，不再对它监控/调用。
- 每日 01:00 定时抓取，任务 id `2cfb0f31-b11d-4802-838c-e4f925d41f8a`（Belgrade Estate Daily Scrape，cron `0 1 * * *` tz=Europe/Belgrade，agentTurn 执行 `bash ~/Projects/BelgradeEstate/run_all.sh`），指令统一为 `bash ~/Projects/BelgradeEstate/run_all.sh`。
- ⚠️ 旧任务 id `e89c7fb9-...` 已在 2026-10-02 迁移后丢失（网关 automations 中不存在），已重建。
- 生成看板：`/Volumes/Data2TB/ai_output/BelgradeEstate/stan_<日期>/index_<日期>.html`、`/Volumes/Data2TB/ai_output/BelgradeEstate/kuca_<日期>/index_<日期>.html`。
- 新增判定信号读 `data/kuca_temp.json`（kuca）；公寓数据在 `data/stan_temp.json`。

## 5. 三源解析要点（已修复的坑，勿回退）

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

## 6. URL 路径铁律（404 教训）

- **静态服务根目录 = OUTPUT_BASE（`/Volumes/Data2TB/ai_output/BelgradeEstate`）**，不是今日输出目录。
- **永久公网域名（2026-09-28 起）**：`BASE_URL = "https://estate.onebitlight.xyz"`，由 Cloudflare Zero Trust Tunnel 生产级架构承载（隧道后台服务名 `mac-mini`），已彻底替换旧的不稳定临时 loca.lt 隧道。**禁止再引入/依赖任何临时穿透工具（localtunnel/loca.lt）**。
- 所以所有外链必须带 `stan_<日期>/` 或 `kuca_<日期>/` 前缀：
  - 公寓看板：`{BASE_URL}/stan_<日期>/index_<日期>.html`
  - 独栋看板：`{BASE_URL}/kuca_<日期>/index_<日期>.html`（例：`https://estate.onebitlight.xyz/kuca_2026-09-28/index.html`）
  - 详情页：`{BASE_URL}/stan_<日期>/details/house_N.html`（或 kuca_…）
- 推微信前应自检：`urllib.request.urlopen(链接)` 返回 HTTP 200。
- Cloudflare 隧道指向本地 `localhost:8765`，root 即 `/Volumes/Data2TB/ai_output/BelgradeEstate/`，无边缘缓存（`cf-cache-status: DYNAMIC`）。
- ⚠️ `scraper_kuca.py` / `send_wechat.py` 内的 `BASE_URL` 均已统一为 `https://estate.onebitlight.xyz`；任何新增爬虫/报告脚本也必须用它，禁止再用旧 loca.lt 域名。

## 7. 端口 8765 冲突（勿重蹈）

- guardian 常驻服务**已占用** `127.0.0.1:8765`（root = `/Volumes/Data2TB/ai_output/BelgradeEstate`），且有 live 公网 URL（`logs/guardian_state.json`）。
- 完整跑 `main()` 时 `start_local_server_and_tunnel` 会在 8765 起新服务 → 端口冲突报 `OSError: Errno 48`，导致推送被跳过。
- **正确做法**：复用 guardian 已有 public_url（读 `logs/guardian_state.json` / `logs/tunnel_url.txt`），直接调 `push_all` 推送，不要自己再起隧道。

## 8. 看板样式要点（卡片渲染 v2 — commit `c79c669`）

- 标头：`BELGRADE RENTALS`（原 `Belgrade · Chinese Edition`）。
- 标题不含 `#房源ID`（该编号 = 网站原生 Listing ID，与 URL 尾部一致，无展示价值，已从 title 移除；去重仍用 `id` 字段）。
- **卡片标题（h3）= 真实塞语片区 + 中文翻译 + 户型/特色**，如 `Učiteljsko naselje 兹韦兹达拉 · 一房`、`Žarkovo 丘卡里察 · 全配家具`。不再用千篇一律的"贝尔格莱德精选公寓"。
- **卡片副标题（feat）= 动态核心参数**，用 `·` 分隔：面积 m² · 几房 · 供暖（集中/燃气/电暖） · 车位/家具等，如 `50 m² · 两房半 · 全配家具`。不再显示"精选房源，交通便利"。
- 片区中文对照：`AREA_ZH` 词典（含行政区+热门微片区），`area_zh()` 查表，`rooms_zh()` 户型翻译，`halo_parse_feature_text()` 从塞语描述/slug 识别供暖/车位/家具/电梯/阳台/新楼/即刻入住。
- HaloOglasi 每张卡仅本卡片子树内提取：`halo_card_places()`（区位）、`halo_card_features()`（Kvadratura/Broj soba/Spratnost）、`halo_card_desc()`（描述）、`halo_build_item()`（组装 item）。CityExpert 用 `extract_cityexpert_area()` 从 url slug/location 识别片区。
- `card_render.py` 的微信图文卡显示 street，不含 #编号。

## 9. 微信推送格式（2026-10-09 用户手动固化，唯一标准）

**统一汇总单条推送**（不再分类型独立推送），格式：
```
🌇 【Belgrade房源推送】
📅  日期：YYYY-MM-DD

🏢 公寓 (Stan)：新增 N 套
💰 价格：X€ - Y€/月
🌐 看板：https://estate.onebitlight.xyz/stan_<date>/index.html

🏡 独栋 (Kuća)：新增 N 套
💰 价格：X€ - Y€/月
🌐 看板：https://estate.onebitlight.xyz/kuca_<date>/index.html

👇 查看近期全部房源：
🌐 列表：https://estate.onebitlight.xyz
```

### 推送入口与调用链
- **唯一主入口**：`push_daily_summary(date_str, stan_items, kuca_items, stan_count, stan_min, stan_max, kuca_count, kuca_min, kuca_max)`
- **调用方**：`run_all.sh` 第3阶段读取 `data/stan_temp.json` + `data/kuca_temp.json` → 调用 `push_daily_summary(stan_items=..., kuca_items=...)`
- **兼容旧接口**：`push_all()` 内部转调 `push_daily_summary()`；CLI 入口 `send()` 支持 argparse 传参

### 价格区间逻辑
- **优先级**：实际房源数据 (`extract_price_range()`) > 预设检索区间 (`PRESET_PRICE_RANGE`：公寓 350-650€、独栋 500-1300€) > "暂无价格信息"
- `format_price_range()` 统一格式化，当价格来自预设区间时调用方可通过 `price_str` 参数传入自定义标记

### 底层发送与容错
- `_run_openclaw(msg)`：`openclaw message send --channel openclaw-weixin --target o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat`
- 120s 超时，3 轮重试/5s 退避
- ret=-2 → Session 未激活，提示用户发消息激活

### 配置常量（模块级，修改需同步）
- `WECHAT_TARGET = "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat"`
- `CHANNEL = "openclaw-weixin"`
- `BASE_URL = "https://estate.onebitlight.xyz"`
- `PRESET_PRICE_RANGE = {'stan': (350, 650), 'kuca': (500, 1300)}` — 需与 `scraper_stan.py`/`scraper_kuca.py` 的 MIN_PRICE/MAX_PRICE 保持一致

## 10. Cloudflare 隧道自动守护（2026-09-28 更新为永久域名）

- **2026-09-28 架构更新**：放弃临时 loca.lt 隧道，改用 **Cloudflare Zero Trust Tunnel** 绑定的永久公网专属域名 `https://estate.onebitlight.xyz`（服务名 `mac-mini`，本地 localhost:8765 → `/Volumes/Data2TB/ai_output/BelgradeEstate/`）。
- 动态 H5 报告路径格式：`https://estate.onebitlight.xyz/{house_type}_{YYYY-MM-DD}/index.html`（如 `.../kuca_2026-09-28/index.html`）。

- **脚本**: `~/Projects/BelgradeEstate/keep_tunnel_alive.sh`（每 30s 检测网络 + 隧道进程 + 域名可达性，失效时自动重启并更新 `logs/guardian_state.json`）
- **LaunchAgent**: `~/Library/LaunchAgents/com.guardian.tunnel.plist`（RunAtLoad + KeepAlive，Mac 重启自动拉起）
- **当前公网 URL**: 永久域名 `https://estate.onebitlight.xyz`（不再随隧道重启变化），运行时仍写 `logs/guardian_state.json`

## 11. 静态服务目录与守护铁律（2026-10-10 固化，勿违反）

### 静态服务目录规范
- **房产看板静态文件根目录**：`/Volumes/Data2TB/ai_output/BelgradeEstate`（**绝对路径，不可变更**）。
- **本地服务绑定**：必须在上述绝对路径下绑定 `127.0.0.1:8765` 端口运行。
- **严禁**在项目根目录 `~/Projects/BelgradeEstate` 或其他路径下运行 8765 端口服务，否则 Cloudflare Tunnel 路由的外网访问将报 404/502。
- **Python 3.9 警告**：`python3 -m http.server --directory` 参数在该版本不可靠（实测 cwd 会落在 `/`），**必须**使用 `os.chdir()` 内联代码方案：
  ```python
  import os, http.server, socketserver
  os.chdir('/Volumes/Data2TB/ai_output/BelgradeEstate')
  PORT = 8765
  Handler = http.server.SimpleHTTPRequestHandler
  with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as httpd:
      print('Serving ' + os.getcwd() + ' on port ' + str(PORT), flush=True)
      httpd.serve_forever()
  ```

### 守护保活机制
- **保活脚本**：`~/Projects/BelgradeEstate/keep_static_alive.sh`（v3，2026-10-10 重构）。
- **防冲突机制**：脚本通过 `lsof -ti ":8765"` 获取 PID，再用 `lsof -p $PID | grep cwd` 检查工作目录。只有当端口空闲或存在错误的 cwd 进程时才发起重启。如果端口已被正确路径占用（cwd = `/Volumes/Data2TB/ai_output/BelgradeEstate`），**直接跳过，绝不重复创建进程或误杀正常进程**。
- **LaunchAgent**：`~/Library/LaunchAgents/com.guardian.tunnel.plist`（RunAtLoad + KeepAlive，Mac 重启自动拉起保活脚本）。

### Tunnel 分工
- **Cloudflare Tunnel 完全由系统 LaunchDaemon 接管**：`/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`（root 用户、token-file 模式）。
- **固定域名** `estate.onebitlight.xyz` → Cloudflare Zero Trust Dashboard Public Hostname → `http://127.0.0.1:8765`。
- **保活脚本不再干预隧道**：`com.guardian.tunnel.plist` 仅负责静态服务的保活，隧道生命周期由 `com.cloudflare.cloudflared` LaunchDaemon 统一管理。
- **域名访问异常排查优先级**：
  1. 先检查 8765 静态服务进程是否在运行 + cwd 是否正确：`lsof -tiTCP:8765 -sTCP:LISTEN && lsof -p $(lsof -tiTCP:8765 -sTCP:LISTEN) | grep cwd`
  2. 再检查 Cloudflare Tunnel：`ps aux | grep "cloudflared tunnel"`
  3. 切勿擅自更改 `keep_static_alive.sh` 中的 `STATIC_ROOT`。

## 12. CityExpert slug 补全修复（commit `7fc2696`，2026-09-25）

- **根因**: 改 `fetch_cityexpert` 适配 ng-state 时丢了 slug，导致房源链接 404
- **修复**: 用 `street/structure/municipality` 拼接完整 slug 格式，`item_url` 为 `/belgrade/{pid}/{slug}`
- **注意**: `structure` 偶有 `'OTHER'` 非数字值导致 `X-rooms` 失败，后续需加强容错
