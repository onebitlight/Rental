# 贝尔格莱德房源爬虫 — 技术沉淀备忘录

> 记录项目开发过程中排查并固化的核心架构决策、反直觉陷阱、以及关键修复方案。
> 最后更新：2026-10-11

---

## 1. CityExpert 图片 CDN 分桶（Bucket）规则

### 问题现象
部分房源详情页/缩略图返回 **404**。

### 根本原因
CityExpert 的图片 CDN 按 `prop_id`（房源 ID）分组存储，旧代码使用了错误的分桶粒度公式：

```
❌ 错误：bucket = (prop_id // 10000) * 10000   （以"万"为单位）
✅ 正确：bucket = (prop_id // 1000) * 1000    （以"千"为单位）
```

### 固化结论

**完整图片 URL 构造规则：**

```
https://img.cityexpert.rs/properties/470x/{bucket}/{prop_id}/slike/{coverPhoto}
```

其中：
- `bucket = int(int(prop_id) / 1000) * 1000`
- `prop_id` 来自 `ng-state` JSON 中的 `propId` 或 `uniqueID`
- `coverPhoto` 是 `ng-state` 中 `coverPhoto` 字段的纯文件名（不含路径前缀）

**验证方法：** 用抓取到的列表页数据拼出 URL，对多条不同 `prop_id` 的房源做 `curl -sI`，确认全部返回 `HTTP/2 200`。

### 注意事项
- CityExpert 目前**仅在贝尔格莱德有公寓数据**；`/houses` 和 `/commercial` 子页面返回 0 条结果
- `bucket` 分桶粒度是基于 CDN 实际目录结构反推的，不是从 API 文档获取的——如果将来 CDN 结构变化，需重新验证

---

## 2. HaloOglasi 动态渲染与字段提取规则

### 问题现象
所有 HaloOglasi 房源（公寓/独栋/商铺）的：
- **面积（Kvadratura）**：全部显示为 `None`（看板上渲染为"未标明"）
- **房间数（Broj soba）**：全部显示为默认值 `1.0` 间

### 根本原因

HaloOglasi 详情页的核心字段（面积、房间数）通过 **前端 JavaScript 动态渲染**。

静态 HTML 中只有空的占位 `<span>` 标签：

```html
<li>
  <span class="field-name">Kvadratura</span>
  <span class="field-value">
    <span id="plh11"></span>   <!-- 空！值由 JS 动态注入 -->
    <script>...</script>
  </span>
</li>

<li class="last-item">
  <span class="field-name">Broj soba</span>
  <span class="field-value">
    <span id="plh12"></span>   <!-- 空！值由 JS 动态注入 -->
    <script>...</script>
  </span>
</li>
```

使用 `cloudscraper` + `BeautifulSoup` 只能获取静态 HTML，**无法执行 JavaScript**，因此 `soup.get_text()` 在 `Kvadratura` 和 `Broj soba` 标签附近找不到任何数值。

### 固化结论

#### 正确做法：优先从 Embedded JSON 提取

数据实际上已经内嵌在页面 `<script>` 标签的 JSON 对象 `QuidditaEnvironment.CurrentClassified` 中：

| 字段 | JSON Key | 格式 | 适用范围 |
|------|----------|------|----------|
| 面积 | `"kvadratura_d"` | 数字（如 `40.0`） | 公寓 / 独栋 / 商铺 |
| 房间数 | `"broj_soba_s"` | 字符串（如 `"1.0"`） | 公寓 / 独栋 |
| 装修状态 | `"namestenost_s"` | 字符串 | 全部 |
| 地段 | `"mikrolokacija_s"` | 字符串 | 全部 |
| 区/市 | `"lokacija_s"` | 字符串（如 `"Opština Čukarica"`） | 全部 |
| 街道 | `"ulica_t"` | 字符串 | 全部 |

**提取正则（跨房源类型通用）：**

```python
# 面积（适用于 stan / kuca / lokal）
m_kv = re.search(r'"kvadratura_d"\s*:\s*([\d.]+)', html)
if m_kv:
    size = float(m_kv.group(1))

# 房间数（仅适用于 stan / kuca，lokal 无此字段）
m_soba = re.search(r'"broj_soba_s"\s*:\s*"([\d.]+)"', html)
if m_soba:
    rooms = int(float(m_soba.group(1)))  # 或保留原始 float
```

**搜索范围：** 对 `cloudscraper.get()` 返回的原始 `response.text`（`html` 字符串）直接做正则，**不要**在 `soup.get_text()` 结果的纯文本中搜索——`<script>` 标签的内容不被 `get_text()` 包含。

#### 萃取优先级（所有类型通用）

```
1. 🎯 Embedded JSON（正则穿透 <script> 标签）         ← 首选，命中率最高
2. DOM 遍历（class='field-name' / product-features）  ← 兜底
3. JSON-LD（type='application/ld+json'）              ← 兜底
4. 全文正则（标题/URL slug）                           ← 最后兜底
```

#### 当前实现状态

| 文件 | 函数 | 是否已修复 |
|------|------|-----------|
| `scraper_stan.py` | `parse_halo_detail()` | ✅ 2026-10-11 |
| `scraper_kuca.py` | `parse_halo_kuca_detail()` | ✅ 2026-10-11 |
| `scraper_lokal.py` | `parse_halo_lokal_detail()` | ✅ 2026-10-11 |

---

## 3. HaloOglasi 列表页卡片面积提取的字符陷阱

### 问题现象
从列表页 `.product-features li` 中提取面积时，正则 `'m²' in txt` 匹配失败。

### 根本原因
HaloOglasi 列表页的面积字符串使用了**非标准 Unicode 字符**：

```
原始文本：  "83\xa0m2Kvadratura"
            ↑
            NBSP (U+00A0, 非断空格) + m2 (普通 ASCII '2')

而不是：    "83 m² Kvadratura"
                  ↑
                  U+00B2 (上标 2)
```

旧代码 `if 'm²' in txt` 用 Unicode 上标 `²` 做检测，而实际页面上是 `\xa0m2`（非断空格 + 普通 `m2`），导致永远不匹配。

### 固化结论

对 HaloOglasi 列表页卡片文本的面积匹配，应使用 **双 mode 检测**：

```python
if 'm2' in txt or 'm²' in txt:
    size = parse_num(txt)
```

### 注意事项
- 这个问题仅影响从列表页卡片直接提取面积的场景（商铺 scraper 原先的模式）
- **现在所有类型的首选方案都是穿透详情页从 Embedded JSON 提取**，卡片级提取仅为兜底
- 其他网站的 Unicode 陷阱：东欧/巴尔干网站常用 NBSP（`\xa0`）作为千位分隔符，也常见非标准上标/下标字符

---

## 4. 商铺（Lokal）的特殊性

### 字段差异
与公寓/独栋不同，商业房源**没有"房间数"（Broj soba）指标**：

- `"broj_soba_s"` 字段在商铺详情页的 Embedded JSON 中**不存在**
- `rooms` 字段应明确设置为 Python `None`（不要设默认值 `1.0`）

### 卡片渲染差异
`card_render.py` 中处理：

```python
# ❌ 旧逻辑：rooms=None 是 Python falsy，会掉到 "精选"
structure = item.get('structure') or item.get('rooms') or "精选"

# ✅ 正确：区分 None 和 falsy
structure_raw = item.get('structure') or item.get('rooms')
structure = structure_raw if structure_raw is not None else "精选"

# 商铺卡片不显示房间行
if structure_raw is not None and RENT_TYPE != 'lokal':
    # 显示 "🚪 房间: {structure} 间"
```

---

## 5. Python 3.9.6 `--directory` 参数陷阱

### 问题现象
```bash
python3 -m http.server 8765 --directory /Volumes/Data2TB/ai_output/BelgradeEstate
```
服务器启动成功但返回 **404**，`lsof` 显示进程 cwd 为 `/` 而非目标目录。

### 根本原因
macOS 自带的 Python 3.9.6 编译版本中，`http.server` 的 `--directory` 参数存在 bug，不会正确 `chdir` 到目标目录。

### 固化结论
**永远不要在 Python 3.9 上使用 `--directory` 参数**，使用内联 `os.chdir()` 替代：

```bash
python3 -c "
import os, http.server, socketserver
os.chdir('/Volumes/Data2TB/ai_output/BelgradeEstate')
PORT = 8765
Handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as httpd:
    print('Serving ' + os.getcwd() + ' on port ' + str(PORT), flush=True)
    httpd.serve_forever()
" &>/tmp/static_server.log &
```

**验证方法：**
```bash
lsof -p $(lsof -tiTCP:8765 -sTCP:LISTEN) | grep cwd
# 必须输出: cwd  DIR  ... /Volumes/Data2TB/ai_output/BelgradeEstate
```

---

## 6. Cloudflare Tunnel 与静态服务器的守护架构

### 当前稳定架构（2026-10-10）

| 组件 | 位置 | 管理方式 |
|------|------|----------|
| 静态 HTTP 服务器 | Python `http.server` on `:8765` | `keep_static_alive.sh` 守护（LaunchAgent） |
| Cloudflare Tunnel | `cloudflared tunnel run --token-file` | `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` |
| 公网域名 | `https://estate.onebitlight.xyz` | Cloudflare Zero Trust Dashboard |

### 关键约束
- **Tunnel 由系统 LaunchDaemon（root）管理**，不要在守护脚本中 `spawn cloudflared tunnel --url`
- **静态服务器不能通过 LaunchDaemon 启动**（APFS 外置盘权限），必须由用户 session LaunchAgent 管理
- **服务器必须用 `os.chdir()` 内联方案**，不能用 `--directory`
- 检测规则：`lsof -iTCP:8765 -sTCP:LISTEN` 如出现两个 Python 进程（一个 cwd 正确，一个 cwd `/` 且绑定 `*:8765`），杀掉 cwd 为 `/` 的那个

---

## 7. 跨日去重历史文件铁律

### 文件清单

| 房源类型 | 历史文件 | 数据格式 |
|----------|----------|----------|
| 公寓 (stan) | `data/history_stan.json` | JSON 数组 `["key1", "key2", ...]` |
| 独栋 (kuca) | `data/history_kuca.json` | JSON 数组 |
| 商铺 (lokal) | `data/history_lokal.json` | JSON 数组 |

### 铁律
- **单一累积文件**：历史文件必须是单调递增的单一文件，禁止按日期分片（如 `history_kuca_2026-10-11.json`）——分片会导致跨日去重失效
- **双重 Key 去重**：每个新增房源需同时将 `url` 和 `id` 两个 key 写进历史集
- **全局跨源去重**：同一房源即使被不同来源（CityExpert / HaloOglasi）收录，也因 URL/ID 命中历史而被过滤

---

## 相关文件索引

| 文件 | 说明 |
|------|------|
| `PROJECT_NOTES.md` | 项目运行状态、命令、配置概览 |
| `DEVELOPER_NOTES.md` | (本文件) 技术陷阱 & 架构决策沉淀 |
| `SKILL.md` | 技能定义（`~/.openclaw/agents/main/agent/workshop-skills/belgrade-rental-scraper/`） |
| `data/` | 运行数据（历史、去重、今日待推送） |
| `logs/` | 守护脚本运行日志 |