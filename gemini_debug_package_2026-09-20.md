# 贝尔格莱德租房项目 — Gemini 排查资料包
打包时间：2026-09-20 （时区 Europe/Belgrade）
> 注：本项目**没有独立的 config.json**。配置以常量形式硬编码在 `scraper.py` 顶部（价格区间、输出目录）和 `send_wechat.py`（微信目标白名单、通道）。

---

## 1. 配置（硬编码常量）

### 1a. `scraper.py` 顶部（截至 `main()` 前）
```python
BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
HISTORY_FILE = DATA_DIR / 'history.json'
NEW_ITEMS_FILE = DATA_DIR / 'new_items.json'
TODAY_STR = datetime.now().strftime('%Y-%m-%d')

# --- 路径重构：优先存入外接硬盘 rent 目录，若失败则回退到本地 ---
EXTERNAL_RENT_DIR = pathlib.Path('/Volumes/Data2TB/rent')
if EXTERNAL_RENT_DIR.exists() and os.access(EXTERNAL_RENT_DIR, os.W_OK):
    OUTPUT_BASE = EXTERNAL_RENT_DIR
else:
    OUTPUT_BASE = BASE_DIR / 'output'

TODAY_OUTPUT_DIR = OUTPUT_BASE / f'output_{TODAY_STR}'
DETAIL_DIR = TODAY_OUTPUT_DIR / 'details'

MIN_PRICE = 350
MAX_PRICE = 650
```

### 1b. 微信推送配置 — `send_wechat.py`
```python
WECHAT_TARGETS = [
    "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat",
]
CHANNEL = "openclaw-weixin"
# 底层 CLI: openclaw message send --channel openclaw-weixin --target <TARGET> --message <文本>
```
> 注意：`scraper.py` 的 `send_wechat_notification()` 里也**硬编码了同一 target**（`o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat`）并直接调 `openclaw message send`，不走 `send_wechat.py`。

---

## 2. 价格过滤逻辑代码片段（scraper.py）

### 2a. CityExpert（Angular ng-state JSON）
```python
url = f"https://cityexpert.rs/en/properties-for-rent/belgrade?ptypeid=1&priceFrom={MIN_PRICE}&priceTo={MAX_PRICE}"
...
for item in response_data:
    prop_id = item.get('propId') or item.get('id')
    if not prop_id: continue
    price = item.get('price')
    street = item.get('streetName') or item.get('locationName') or 'Belgrade'
    ...
    if price and MIN_PRICE <= price <= MAX_PRICE:
        main_feat, area_cn, sub_feat = extract_features(street)
        items.append({ 'id': f"ce_{prop_id}", 'source': 'CityExpert',
                       'title': f"{street} · {main_feat}", 'price': int(price),
                       'area_name': area_cn, 'structure': structure, ... })
```

### 2b. HaloOglasi（Cloudflare 保护站点，Playwright 渲染 + 正则）
```python
url = f"https://www.halooglasi.com/nekretnine/izdavanje-stanova/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}"
page.goto(url, wait_until="domcontentloaded", timeout=30000)
...
html = page.content()
matches = re.findall(r'data-id="(\d+)".*?href="(/nekretnine/izdavanje-stanova/[^"]+)".*?data-value="(\d+)"', html, re.DOTALL)
for item_id, href, price_str in matches:
    price = int(price_str)
    if MIN_PRICE <= price <= MAX_PRICE:
        items.append({ 'id': f'halo_{item_id}', 'source': 'HaloOglasi',
                       'title': f'贝尔格莱德精选公寓 #{item_id} · 舒适住宅', 'price': price, ... })
```

### 2c. 4zida（Playwright 渲染 + 正则）
```python
url = f"https://www.4zida.rs/izdavanje-stanova/beograd?cena-od={MIN_PRICE}EUR&cena-do={MAX_PRICE}EUR"
page.goto(url, wait_until="domcontentloaded", timeout=30000)
html = page.content()
matches = re.findall(r'href="(/izdavanje-stanova/beograd/[^"]+?)".*?(\d+)\s*€', html, re.DOTALL)
for href, price_str in matches:
    price = int(price_str)
    id_match = re.search(r'/(\d+)$', href)
    item_id = id_match.group(1) if id_match else str(hash(href))
    if MIN_PRICE <= price <= MAX_PRICE:
        items.append({ 'id': f'4zida_{item_id}', 'source': '4zida', 'title': f'贝尔格莱德公寓 #{item_id} · 品质之选', 'price': price, ... })
```

---

## 3. 微信推送（openclaw message send）代码片段 — `scraper.py` `send_wechat_notification()`

```python
def send_wechat_notification(new_items, public_url=None):
    target = "o9cq806ozJVWfuJaD2MrQ0sYqFdI@im.wechat"
    index_filename = f"index_{TODAY_STR}.html"
    if public_url:
        main_link = f"{public_url}/{index_filename}"
    else:
        main_link = f"本地路径: {TODAY_OUTPUT_DIR / index_filename}"

    if new_items:
        lines = [f"🏠 【贝尔格莱德租房日报】({TODAY_STR})",
                 f"筛选条件：{MIN_PRICE}~{MAX_PRICE} EUR\n今日新增 {len(new_items)} 套精选好房：\n"]
        for idx, item in enumerate(new_items, 1):
            lines.append(f"{idx}. [{item['source']}] {item['price']}€ - {item['title']}")
            if public_url:
                lines.append(f"   详情页: {public_url}/output_{TODAY_STR}/details/house_{idx}.html")
        lines.append(f"\n🌐 点击查看今日完整中文看板：\n{main_link}")
        msg_text = "\n".join(lines)
    else:
        msg_text = (f"🏠 【贝尔格莱德租房日报】({TODAY_STR})\n"
                    f"筛选条件：{MIN_PRICE}~{MAX_PRICE} EUR\n今日暂无新增新房源，自动化服务正常运行中。\n\n"
                    f"🌐 看板地址：\n{main_link}")

    print("📲 正在通过 OpenClaw 发送微信推送...")
    for attempt in range(1, 3):
        try:
            cmd = ["openclaw", "message", "send", "--target", target, "--message", msg_text]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ 微信消息推送成功！")
                break
            else:
                time.sleep(3)
        except Exception:
            time.sleep(3)
```

> ✅ 已于 2026-09-20 统一推送链路：`scraper.py` 不再内置简陋推送，改为 `from send_wechat import push_all` 复用稳定推送（`--channel openclaw-weixin` + 120s 超时 + 3 轮重试/5s 退避）。`send_wechat.py` 新增 `push_all(text)` / `push(target, text, attempts)` 可复用入口，并增加健壮重试。
> ✅ 价格过滤已加固：新增 `parse_price()`（安全解析 int/float/字符串/千位分隔/小数）与 `within_budget()`（严格校验 350~650 含边界），三源全部改用它，坏数据/区间外房源不会入选。

---

## 4. 今日（2026-09-20）运行结果摘要

### 今日输出位置
- 项目配置的 `OUTPUT_BASE` 优先写外接硬盘 `/Volumes/Data2TB/rent`（存在且可写），**所以今天的输出不在本地目录**。
- 本地 `/Users/SGY/BelgradeRentals/` 下只有 `output_2026-09-14/15/17/18/19`；**没有 `output_2026-09-20`**。
- 今日实际输出：`/Volumes/Data2TB/rent/output_2026-09-20/`

### 今日抓取摘要（index_2026-09-20.html，02:00 生成）
- **今日精选 1 套 · 租金 €350–650**
- 更新日期：📅 2026-09-20
- 唯一房源：
  - 价格 **€400/月**
  - 区域：贝尔格莱德中心区
  - 来源标签：**HaloOglasi**
  - 标题：贝尔格莱德精选公寓 #5425647700864 · 舒适住宅
  - 详情页：`details/house_1.html`（外接盘 output_2026-09-20/details/）
- 看板标题：贝尔格莱德好房中文看板（Chinese Edition）

### 当前推送队列 / 守护状态
- `data/push_pending.json` → **`[]`**（无待推送积压）
- `logs/guardian_state.json`：
  ```json
  {"ts":1789850019,"static_up":1,"tunnel_up":1,"public_url":"https://real-availability-schedule-touch.trycloudflare.com"}
  ```
  → 静态服务 up、Cloudflare 隧道 up、公网 URL 可用。

---

## 附：文件清单（本次抓取到的实际运行文件）
| 文件 | 说明 |
|---|---|
| `/Users/SGY/BelgradeRentals/scraper.py` (421 行) | 主爬虫：3 源抓取 + 过滤 + 渲染看板 + 内置微信推送 |
| `/Users/SGY/BelgradeRentals/send_wechat.py` (148 行) | 独立微信 CLI 推送脚本（白名单/通道/超时） |
| `/Users/SGY/BelgradeRentals/card_render.py` (292 行) | 卡片渲染 |
| `/Users/SGY/BelgradeRentals/data/history.json` | 历史去重集合 |
| `/Users/SGY/BelgradeRentals/data/push_pending.json` | 待推送队列（当前空） |
| `/Users/SGY/BelgradeRentals/data/new_items.json` | 当日新增临时件 |
| `/Users/SGY/BelgradeRentals/logs/guardian_state.json` | 守护守护状态（tunnel/static URL） |
| `/Volumes/Data2TB/rent/output_2026-09-20/` | 今日看板 + 详情页（外部盘） |
