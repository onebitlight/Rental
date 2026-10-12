# -*- coding: utf-8 -*-
import os, sys, json, re, time, math
import pathlib
from datetime import datetime
import cloudscraper
from bs4 import BeautifulSoup

try:
    from send_wechat import push_all, WECHAT_TARGETS
except ImportError:
    def push_all(text=None, items=None):
        print(f"📱 [微信推送] {text or items}")
        return True
    WECHAT_TARGETS = ["default"]

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE = DATA_DIR / 'history_stan.json'
NEW_ITEMS_FILE = DATA_DIR / 'new_items.json'

TODAY_STR = datetime.now().strftime('%Y-%m-%d')

OUTPUT_BASE = pathlib.Path('/Volumes/Data2TB/ai_output/BelgradeEstate')
if not (OUTPUT_BASE.exists() and os.access(OUTPUT_BASE, os.W_OK)):
    OUTPUT_BASE = BASE_DIR / 'output'

TODAY_OUTPUT_DIR = OUTPUT_BASE / f'stan_{TODAY_STR}'
TODAY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ENABLE_STAN_SCRAPER = True

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

MIN_PRICE = 350
MAX_PRICE = 650
MAX_PAGES = 3

# === 4zida.rs 专属页数限制 ===
# 4zida 使用 Next.js RSC 架构，列表页仅输出 ~20 条服务端渲染结果，
# 剩余内容通过 JavaScript infinite scroll 加载，stranica=N 参数无效。
# 设置为 1 以避免重复请求同一页数据。
MAX_PAGES_4ZIDA = 1

AREA_EN_LIST = [
    "Novi Beograd", "Zemun", "Vračar", "Stari grad", "Savski venac", 
    "Čukarica", "Voždovac", "Zvezdara", "Palilula", "Rakovica", "Surčin", "Dedinje", "Senjak", "Dorćol"
]

# === 4zida.rs 区域名映射（塞语 → 英文） ===
FOURZIDA_AREA_MAP = {
    "novi-beograd": "Novi Beograd",
    "beograd-na-vodi": "Savski venac",
    "zemun": "Zemun",
    "vracar": "Vračar",
    "stari-grad": "Stari grad",
    "savski-venac": "Savski venac",
    "cukarica": "Čukarica",
    "vozdovac": "Voždovac",
    "zvezdara": "Zvezdara",
    "palilula": "Palilula",
    "rakovica": "Rakovica",
    "surcin": "Surčin",
    "dedinje": "Dedinje",
    "senjak": "Senjak",
    "dorcol": "Dorćol",
    "centar": "Stari grad",
    "karaburma": "Palilula",
    "banovo-brdo": "Čukarica",
    "mirijevo": "Zvezdara",
    "konjarnik": "Voždovac",
}

def detect_area(blob):
    for en in AREA_EN_LIST:
        if en.lower() in blob.lower(): 
            return en
    return "Belgrade"


def _detect_4zida_area_from_slug(url_slug):
    """从 4zida.rs URL slug 提取标准化区域名。
    
    示例 URL: /izdavanje-stanova/crveni-krst-vracar-vracar-beograd/trosoban-stan/6a99...
    提取 'vracar' 部分后映射为 'Vračar'。
    """
    slug = url_slug.lower()
    # 匹配 known areas
    for slug_key, area_en in FOURZIDA_AREA_MAP.items():
        if slug_key in slug:
            return area_en
    # fallback: 用 detect_area 在 slug 上匹配
    return detect_area(slug)

def load_history():
    if HISTORY_FILE.exists():
        try:
            raw = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return raw
            # Legacy format: list (or set serialized as list) — auto-convert to dict
            if isinstance(raw, list):
                return {str(k): TODAY_STR for k in raw if k}
            return {}
        except:
            return {}
    return {}

def save_history(history_dict):
    HISTORY_FILE.write_text(json.dumps(history_dict, ensure_ascii=False, indent=2), encoding='utf-8')

def item_key(item):
    return item.get('url') or item.get('id') or ''

def parse_price(val):
    if val is None or isinstance(val, bool):
        return None
    try:
        s = str(val).replace('€', '').replace('EUR', '').replace('eur', '').strip()
        s = s.replace(',', '')
        m = re.search(r'\d+(\.\d+)?', s)
        if not m: return None
        p = round(float(m.group()))
        return p if p > 0 else None
    except:
        return None

def within_budget(price):
    p = parse_price(price)
    return p is not None and MIN_PRICE <= p <= MAX_PRICE

def fetch_cityexpert():
    items = []
    url = f"https://cityexpert.rs/en/properties-for-rent/belgrade?ptypeid=1&priceFrom={MIN_PRICE}&priceTo={MAX_PRICE}"
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(DEFAULT_HEADERS)
        r = scraper.get(url, timeout=20)
        if r.status_code != 200: return items
        m = re.search(r'<script id="ng-state" type="application/json">(.*?)</script>', r.text, re.S)
        if not m: return items
        data = json.loads(m.group(1))

        def _find_results(obj):
            if isinstance(obj, dict):
                if 'result' in obj and isinstance(obj['result'], list):
                    return obj['result']
                for v in obj.values():
                    res = _find_results(v)
                    if res is not None: return res
            return None

        response_data = _find_results(data) or []
        for item in response_data:
            prop_id = item.get('propId') or item.get('uniqueID')
            if not prop_id: continue
            price = parse_price(item.get('price'))
            if not within_budget(price): continue

            street = item.get('street') or 'Belgrade'
            structure = str(item.get('structure') or '1.0')
            
            cp = item.get('coverPhoto') or ''
            img_url = ""
            if cp:
                try:
                    # CityExpert CDN bucket 分区以 千位 (1000) 为一档，而非万位 (10000)
                    bucket = int(int(prop_id) / 1000) * 1000
                except:
                    bucket = 0
                img_url = f"https://img.cityexpert.rs/properties/470x/{bucket}/{prop_id}/slike/{cp}"

            muni = str(item.get('municipality') or '').lower().replace(' ', '-')
            item_url = f"https://cityexpert.rs/en/properties-for-rent/belgrade/{prop_id}/{muni}"
            
            size = item.get('size')
            parking = bool(item.get('parkingArray'))
            furnished = str(item.get('furnished')) == '1'

            features_list = [f"{structure}室"]
            if size: features_list.append(f"{size}m²")
            if parking: features_list.append("带车位")
            if furnished: features_list.append("含家具")

            items.append({
                'id': f"ce_{prop_id}",
                'source': 'CityExpert',
                'title': f"{street} · 公寓出租",
                'price': price,
                'area_name': detect_area(item.get('municipality') or 'Belgrade'),
                'structure': structure,
                'features': " · ".join(features_list),
                'size': size,
                'image': img_url,
                'parking': parking,
                'publisher': '中介',
                'url': item_url
            })
    except Exception as e:
        print(f"CityExpert 抓取失败: {e}")
    return items

def parse_halo_detail(scraper, href, card_title=""):
    """🚀 HaloOglasi 详情页穿透解析：优先从 embedded JSON 提取，辅以 DOM 兜底"""
    detail_info = {'size': None, 'rooms': '1.0', 'area_name': 'Belgrade'}
    try:
        r = scraper.get(href, timeout=15)
        if r.status_code != 200:
            return detail_info
        
        html = r.text
        soup = BeautifulSoup(html, 'html.parser')
        full_text = soup.get_text()

        # 1. 区域名解析
        detail_info['area_name'] = detect_area(full_text)

        # 2. 🎯 优先从 embedded JSON (QuidditaEnvironment.CurrentClassified) 提取面积和房间数
        #    HaloOglasi 将 Kvadratura/Broj soba 通过 JS 动态渲染到 <span id="plh11/12">，
        #    但原始值已内嵌在 <script> 标签的 JSON 中："kvadratura_d":<num>, "broj_soba_s":"<num>"
        m_kv = re.search(r'"kvadratura_d"\s*:\s*([\d.]+)', html)
        if m_kv:
            val = float(m_kv.group(1))
            if 10 <= val <= 3000:
                detail_info['size'] = val

        m_soba = re.search(r'"broj_soba_s"\s*:\s*"([\d.]+)"', html)
        if m_soba:
            rm_val = float(m_soba.group(1))
            if 1 <= rm_val <= 15:
                detail_info['rooms'] = int(rm_val) if rm_val.is_integer() else rm_val

        # 3. DOM 兜底：遍历表格行/属性列表项，寻找 Kvadratura（处理非标准页面）
        if not detail_info['size']:
            for row in soup.select('tr, li, div.detail-row, div.property-feature'):
                row_text = row.get_text()
                if any(kwd in row_text.lower() for kwd in ['kvadratura', 'površina', 'm²']):
                    m = re.search(r'(\d+(?:\.\d+)?)', row_text.replace(',', '.'))
                    if m:
                        val = float(m.group(1))
                        if 10 <= val <= 1000:
                            detail_info['size'] = val
                            break

        # 4. JSON-LD 兜底
        if not detail_info['size']:
            for tag in soup.find_all('script', type='application/ld+json'):
                try:
                    ld_data = json.loads(tag.string or '')
                    if isinstance(ld_data, dict):
                        floor_size = ld_data.get('floorSize')
                        if isinstance(floor_size, dict):
                            val = floor_size.get('value')
                            if val: detail_info['size'] = float(val)
                except:
                    pass

        # 5. 全局正文正则兜底（面积）
        if not detail_info['size']:
            all_sz = re.findall(r'(\d{2,3}(?:\.\d+)?)\s*m[²2]', full_text, re.I)
            valid_sz = [float(s) for s in all_sz if 10 <= float(s) <= 500]
            if valid_sz:
                detail_info['size'] = valid_sz[0]

        # 6. DOM 兜底（房间数）
        if detail_info['rooms'] == '1.0':
            for row in soup.select('tr, li, div.detail-row'):
                row_text = row.get_text().lower()
                if 'soba' in row_text or 'sobe' in row_text:
                    m_rm = re.search(r'(\d+(?:\.\d+)?)', row_text)
                    if m_rm:
                        detail_info['rooms'] = m_rm.group(1)
                        break

        # 7. 标题兜底（房间数）
        if detail_info['rooms'] == '1.0':
            m_rm_title = re.search(r'(\d+\.\d+|\d)\s*sobn', f"{card_title} {full_text}", re.I)
            if m_rm_title:
                detail_info['rooms'] = m_rm_title.group(1)

    except Exception as e:
        print(f"⚠️ 解析详情页异常 {href}: {e}")
    
    return detail_info

def fetch_4zida():
    """🆕 4zida.rs 房源抓取（Next.js RSC JSON-LD 解析）
    
    数据模型：页面通过 __next_f.push() 将 JSON-LD 格式的 ItemList/RealEstateListing
    注入 <script> 标签。每条 listing 包含：
    - item.name: 街道/区域名称（如 "CRVENI KRST"）
    - item.offers.price: 月租价格（EUR）
    - item.itemOffered.numberOfRooms: 房间数
    - item.itemOffered.floorSize.value: 面积 (m²)
    - item.image.url: 封面图（resizer2.4zida.rs CDN）
    - li.url: 详情页完整 URL（含 24 位 hex adId）
    - 区域名从 URL slug 解析（如 .../vracar-beograd/...）
    - 发布者类型需从详情页 JSON-LD seller 块推断（Organization=中介，Person=个人）
    """
    items = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(DEFAULT_HEADERS)
    
    # 4zida 价格过滤参数：cena_od / cena_do
    url = f"https://www.4zida.rs/izdavanje-stanova/beograd?cena_do={MAX_PRICE}&cena_od={MIN_PRICE}"
    
    for page in range(1, MAX_PAGES_4ZIDA + 1):
        page_url = url if page == 1 else f"{url}&stranica={page}"
        try:
            print(f"🔎 4zida.rs 第 {page}/{MAX_PAGES_4ZIDA} 页...")
            r = scraper.get(page_url, timeout=20)
            if r.status_code != 200:
                break
            
            html = r.text
            
            # ═══ 解析 JSON-LD ItemList ═══
            data = _extract_4zida_itemlist(html)
            if not data:
                print(f"   ⚠️ 未找到 ItemList JSON-LD，跳过")
                break
            
            listings = data.get('itemListElement', [])
            print(f"   📋 获取到 {len(listings)} 条 listing")
            
            if not listings:
                break
            
            for li in listings:
                item_data = li.get('item', {})
                li_url = li.get('url', '')
                
                # 提取 24 位 hex adId
                ad_id_match = re.search(r'/([a-f0-9]{24})(?:/|$|\?)', li_url)
                if not ad_id_match:
                    continue
                ad_id = ad_id_match.group(1)
                
                # 价格
                offers = item_data.get('offers', {})
                price = parse_price(offers.get('price')) if isinstance(offers, dict) else None
                if not within_budget(price):
                    continue
                
                # 名称
                name = item_data.get('name', '').strip()
                
                # 房间数 & 面积
                item_offered = item_data.get('itemOffered', {})
                if isinstance(item_offered, dict):
                    rooms_raw = item_offered.get('numberOfRooms')
                    floor_size = item_offered.get('floorSize', {})
                    size = floor_size.get('value') if isinstance(floor_size, dict) else None
                else:
                    rooms_raw, size = None, None
                
                # 房间数 fallback: URL slug 推断
                if not rooms_raw:
                    rooms_raw = _infer_rooms_from_4zida_slug(li_url)
                rooms = str(rooms_raw) if rooms_raw else '1.0'
                
                # 区域名：从 URL slug 提取
                area_name = _detect_4zida_area_from_slug(li_url)
                
                # 图片
                img_obj = item_data.get('image', {})
                img_url = img_obj.get('url', '') if isinstance(img_obj, dict) else ''
                if img_url and img_url.startswith('//'):
                    img_url = 'https:' + img_url
                
                # 详情页穿透：获取发布者类型
                publisher = _fetch_4zida_publisher(scraper, li_url)
                
                # 面积转换为 int
                size_int = int(size) if size else None
                
                features_list = []
                if rooms_raw:
                    features_list.append(f"{rooms_raw}室")
                if size_int:
                    features_list.append(f"{size_int}m²")
                
                items.append({
                    'id': f"4z_{ad_id}",
                    'source': '4zida.rs',
                    'title': f"{name} · 公寓出租",
                    'price': price,
                    'area_name': area_name,
                    'structure': str(rooms_raw) if rooms_raw else '1.0',
                    'features': " · ".join(features_list) if features_list else "公寓出租",
                    'size': size_int,
                    'image': img_url or "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80",
                    'publisher': publisher,
                    'url': li_url
                })
            
            time.sleep(0.5)
        except Exception as e:
            print(f"4zida.rs 第 {page} 页抓取失败: {e}")
    
    return items


def _extract_4zida_itemlist(html):
    """从 4zida.rs HTML 中提取 ItemList JSON-LD 数据。
    
    Next.js RSC 将 JSON-LD 嵌入 <script> 标签的 __next_f.push() 调用中。
    数据被双重转义（JS 字符串 + JSON 字符串）。
    """
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    for s in scripts:
        if 'RealEstateListing' not in s or 'numberOfRooms' not in s:
            continue
        # 提取 push([...,"{json}"]) 中的 JSON
        m = re.search(r'push\(\[.*?,"(\{.*?\})"\]\)', s, re.S)
        if not m:
            continue
        raw = m.group(1)
        # 去转义
        raw = raw.replace('\\"', '"').replace('\\\\', '\\')
        try:
            data = json.loads(raw)
            # ItemList 可能在 mainEntity 下
            main = data.get('mainEntity', data)
            if isinstance(main, dict) and 'itemListElement' in main:
                return main
            if isinstance(data, dict) and 'itemListElement' in data:
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _infer_rooms_from_4zida_slug(url):
    """从 4zida.rs URL slug 推断房间数。
    
    URL 模式: /.../trosoban-stan/...  → 3
              /.../dvoiposoban-stan/... → 2.5
              /.../dvosoban-stan/... → 2
              /.../jednosoban-stan/... → 1
    """
    room_map = {
        'jednosoban': 1,
        'dvosoban': 2,
        'dvoiposoban': 2.5,
        'trosoban': 3,
        'cetvorosoban': 4,
        'petosoban': 5,
        'sestosoban': 6,
    }
    m = re.search(r'/(jednosoban|dvosoban|dvoiposoban|trosoban|cetvorosoban|petosoban|sestosoban)-stan/', url.lower())
    return room_map.get(m.group(1)) if m else None


def _fetch_4zida_publisher(scraper, listing_url):
    """穿透 4zida.rs 详情页获取发布者类型。
    
    详情页 JSON-LD 包含 #seller 块：
    - @type: Organization → 中介
    - @type: Person → 个人
    若详情页不可达，默认返回 '中介'。
    """
    try:
        r = scraper.get(listing_url, timeout=15)
        if r.status_code != 200:
            return '中介'
        
        html = r.text
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        
        for s in scripts:
            if '#seller' not in s:
                continue
            # 尝试直接 JSON-LD 解析
            if s.startswith('{'):
                try:
                    data = json.loads(s)
                    if data.get('@type') == 'Person':
                        return '个人'
                    elif data.get('@type') == 'Organization':
                        return '中介'
                except json.JSONDecodeError:
                    pass
            # 尝试 __next_f.push 格式
            m = re.search(r'push\(\[.*?,"(\{.*?\})"\]\)', s, re.S)
            if m:
                raw = m.group(1).replace('\\"', '"').replace('\\\\', '\\')
                try:
                    data = json.loads(raw)
                    if data.get('@type') == 'Person':
                        return '个人'
                    elif data.get('@type') == 'Organization':
                        return '中介'
                except (json.JSONDecodeError, TypeError):
                    continue
        
        return '中介'
    except Exception as e:
        print(f"   ⚠️ 获取 4zida 发布者信息异常: {e}")
        return '中介'


# ═══════════════════════════════════════════════════════════
# 🎯 跨平台智能去重与优选引擎
# ═══════════════════════════════════════════════════════════

SIZE_TOLERANCE = 2  # 面积允许 ±2 m² 误差


def _make_fingerprint(item):
    """生成跨平台房源指纹：区域名 + 房间数 + 面积（取整）
    
    指纹用于判定不同网站上的同一条房源是否为同一套房。
    面积取整以允许 ±2 m² 误差的后续模糊匹配。
    """
    area = (item.get('area_name') or item.get('area') or '').strip().lower()
    rooms = item.get('structure') or item.get('rooms') or '1.0'
    try:
        rooms_f = float(rooms)
        rooms_norm = str(int(rooms_f)) if rooms_f.is_integer() else str(rooms_f)
    except (ValueError, TypeError):
        rooms_norm = '1'
    
    size = item.get('size')
    size_rounded = round(float(size)) if size is not None else 0
    
    return f"{area}|{rooms_norm}|{size_rounded}"


def _fingerprint_match(fp1, fp2):
    """检查两个指纹是否匹配（面积允许 ±SIZE_TOLERANCE m² 误差）。"""
    parts1 = fp1.rsplit('|', 2)
    parts2 = fp2.rsplit('|', 2)
    if len(parts1) != 3 or len(parts2) != 3:
        return fp1 == fp2
    
    area1, rooms1, size1_str = parts1
    area2, rooms2, size2_str = parts2
    
    # 区域名必须完全一致
    if area1 != area2:
        return False
    # 房间数必须完全一致
    if rooms1 != rooms2:
        return False
    # 面积允许 ±2 m²
    try:
        size1 = int(size1_str)
        size2 = int(size2_str)
        if size1 == 0 or size2 == 0:
            return size1 == size2
        return abs(size1 - size2) <= SIZE_TOLERANCE
    except ValueError:
        return size1_str == size2_str


def _cross_platform_dedup_prefer(all_items):
    """跨平台去重 + 优选规则。
    
    对于同一套房源在多个网站出现的情况：
    1. 价格优先：选择价格更低的记录
    2. 个人优先：若一处为个人房源，另一处为中介，优先保留个人房源
    
    返回去重优选后的列表。
    """
    # 按指纹分组
    groups = {}  # fingerprint → [item, ...]
    for item in all_items:
        fp = _make_fingerprint(item)
        if fp not in groups:
            groups[fp] = []
        groups[fp].append(item)
    
    preferred = []
    merged_count = 0
    
    for fp, candidates in groups.items():
        if len(candidates) == 1:
            preferred.append(candidates[0])
            continue
        
        # 多个候选 → 执行优选规则
        merged_count += len(candidates) - 1
        sources_before = [c['source'] for c in candidates]
        
        # 规则1: 个人优先 — 个人房源优先于中介
        personal = [c for c in candidates if c.get('publisher') == '个人']
        if personal:
            # 有个人房源 → 从中选价格最低的
            chosen = min(personal, key=lambda c: c['price'])
        else:
            # 全是中介 → 选价格最低的
            chosen = min(candidates, key=lambda c: c['price'])
        
        # 记录合并信息
        chosen['_cross_merged_from'] = sources_before
        chosen['_cross_merged_count'] = len(candidates)
        preferred.append(chosen)
    
    if merged_count > 0:
        print(f"🔄 跨平台去重合并 {merged_count} 条重复房源（优选规则：价低优先 > 个人优先）")
    
    return preferred


def fetch_halooglasi():
    items = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(DEFAULT_HEADERS)
    
    for page in range(1, MAX_PAGES + 1):
        url = f"https://www.halooglasi.com/nekretnine/izdavanje-stanova/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}&page={page}"
        try:
            r = scraper.get(url, timeout=20)
            if r.status_code != 200: break

            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.find_all('div', class_='product-item')
            if not cards: break

            for card in cards:
                item_id = card.get('data-id')
                if not item_id: continue

                price = None
                price_span = card.find('span', attrs={'data-value': True})
                if price_span: price = parse_price(price_span.get('data-value'))
                if not price:
                    price_i = card.select_one('.central-feature i')
                    if price_i: price = parse_price(price_i.text)

                if not within_budget(price): continue

                img_url = ""
                img_tag = card.find('img')
                if img_tag:
                    cand = img_tag.get('src') or img_tag.get('data-src') or ''
                    if cand.startswith('//'): cand = 'https:' + cand
                    elif cand.startswith('/'): cand = 'https://www.halooglasi.com' + cand
                    if 'slike/oglasi' in cand and 'no-image' not in cand:
                        img_url = cand

                link_tag = card.select_one('.product-title a')
                title = link_tag.text.strip() if link_tag else "贝尔格莱德精选公寓"
                href = link_tag.get('href', '') if link_tag else ''
                if href.startswith('/'): href = 'https://www.halooglasi.com' + href

                print(f"   🔗 详情页穿透解析: {title[:30]}...")
                detail_data = parse_halo_detail(scraper, href, card_title=title)
                time.sleep(0.4)

                items.append({
                    'id': f"halo_{item_id}",
                    'source': 'HaloOglasi',
                    'title': title,
                    'price': price,
                    'area_name': detail_data['area_name'],
                    'structure': detail_data['rooms'],
                    'features': f"户型 {detail_data['rooms']}室 · 面积 {detail_data['size'] or '未知'}m²",
                    'size': detail_data['size'],
                    'image': img_url or "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80",
                    'publisher': '中介',
                    'url': href
                })
            time.sleep(1)
        except Exception as e:
            print(f"HaloOglasi 第 {page} 页抓取失败: {e}")
            
    return items

def main():
    if not ENABLE_STAN_SCRAPER:
        return
    
    # ═══════ 三源并行抓取 ═══════
    print("\n📥 [1/3] CityExpert 抓取中...")
    ce_items = fetch_cityexpert()
    print(f"   ✅ CityExpert: {len(ce_items)} 条")
    
    print("\n📥 [2/3] HaloOglasi 抓取中...")
    halo_items = fetch_halooglasi()
    print(f"   ✅ HaloOglasi: {len(halo_items)} 条")
    
    print("\n📥 [3/3] 4zida.rs 抓取中...")
    zida_items = fetch_4zida()
    print(f"   ✅ 4zida.rs: {len(zida_items)} 条")
    
    # ═══════ 跨平台智能去重与优选 ═══════
    all_items = ce_items + halo_items + zida_items
    print(f"\n🔗 三源合计: {len(all_items)} 条，开始跨平台指纹去重...")
    preferred = _cross_platform_dedup_prefer(all_items)
    print(f"   ✅ 优选后: {len(preferred)} 条")
    
    # ═══════ 历史字典对比（同日保留 / 跨日剔除） ═══════
    history = load_history()
    new_items = []
    today_new_count = 0
    
    for item in preferred:
        k = item_key(item)
        if not k:
            continue
        
        prev_date = history.get(k)
        if prev_date is None:
            prev_date = history.get(item['id'])
        
        if prev_date is None:
            # Case A: brand-new — record both url and id keys
            history[k] = TODAY_STR
            if item['id'] and item['id'] != k:
                history[item['id']] = TODAY_STR
            new_items.append(item)
            today_new_count += 1
        elif prev_date == TODAY_STR:
            # Case B: same-day re-scrape — keep
            new_items.append(item)
        else:
            # Case C: older date — skip
            pass
    
    save_history(history)
    
    # ═══════ 清理内部字段后输出 ═══════
    clean_items = []
    for item in new_items:
        clean = {k: v for k, v in item.items() if not k.startswith('_cross_')}
        clean_items.append(clean)
    
    output_data = {
        "meta": {
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "sources": {
                "cityexpert": len(ce_items),
                "halooglasi": len(halo_items),
                "4zida": len(zida_items)
            }
        },
        "items": clean_items
    }
    NEW_ITEMS_FILE.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n✅ 公寓抓取完成！三源合计 {len(all_items)} 条 → 优选 {len(preferred)} 条 → 输出 {len(new_items)} 套（其中全新 {today_new_count} 套）")

# ═══════════════════════════════════════════════════════════
# 🧪 自测模块
# ═══════════════════════════════════════════════════════════

def _self_test():
    """运行核心逻辑的自验证测试。"""
    import traceback
    tests_passed = 0
    tests_total = 0
    
    # Test 1: fingerprint generation
    tests_total += 1
    item1 = {'area_name': 'Vračar', 'structure': '3', 'size': 86}
    item2 = {'area_name': 'Vračar', 'structure': '3', 'size': 87}
    fp1 = _make_fingerprint(item1)
    fp2 = _make_fingerprint(item2)
    assert _fingerprint_match(fp1, fp2), "Fingerprint should match within tolerance"
    tests_passed += 1
    print(f"  ✅ Test 1: fingerprint match (±1m²)")
    
    # Test 2: fingerprint mismatch (different area)
    tests_total += 1
    item3 = {'area_name': 'Zemun', 'structure': '3', 'size': 86}
    fp3 = _make_fingerprint(item3)
    assert not _fingerprint_match(fp1, fp3), "Different area should NOT match"
    tests_passed += 1
    print(f"  ✅ Test 2: fingerprint mismatch (different area)")
    
    # Test 3: fingerprint mismatch (different rooms)
    tests_total += 1
    item4 = {'area_name': 'Vračar', 'structure': '2', 'size': 86}
    fp4 = _make_fingerprint(item4)
    assert not _fingerprint_match(fp1, fp4), "Different rooms should NOT match"
    tests_passed += 1
    print(f"  ✅ Test 3: fingerprint mismatch (different rooms)")
    
    # Test 4: fingerprint exact boundary (±2m²)
    tests_total += 1
    item5 = {'area_name': 'Vračar', 'structure': '3', 'size': 84}
    fp5 = _make_fingerprint(item5)
    assert _fingerprint_match(fp1, fp5), "±2m² should match"
    tests_passed += 1
    print(f"  ✅ Test 4: fingerprint boundary exactly ±2m²")
    
    # Test 5: fingerprint over boundary (±3m²)
    tests_total += 1
    item6 = {'area_name': 'Vračar', 'structure': '3', 'size': 83}
    fp6 = _make_fingerprint(item6)
    assert not _fingerprint_match(fp1, fp6), "±3m² should NOT match"
    tests_passed += 1
    print(f"  ✅ Test 5: fingerprint over boundary (>±2m²)")
    
    # Test 6: cross-platform dedup — price priority
    tests_total += 1
    items_dup = [
        {'id': 'ce_1', 'source': 'CityExpert', 'title': 'Test', 'price': 500, 'area_name': 'Vračar', 'structure': '2', 'size': 50, 'publisher': '中介', 'url': 'http://a'},
        {'id': 'halo_1', 'source': 'HaloOglasi', 'title': 'Test', 'price': 450, 'area_name': 'Vračar', 'structure': '2', 'size': 50, 'publisher': '中介', 'url': 'http://b'},
    ]
    result = _cross_platform_dedup_prefer(items_dup)
    assert len(result) == 1, f"Expected 1 after dedup, got {len(result)}"
    assert result[0]['price'] == 450, "Should pick cheaper"
    tests_passed += 1
    print(f"  ✅ Test 6: cross-platform dedup price priority")
    
    # Test 7: cross-platform dedup — personal priority over price
    tests_total += 1
    items_dup2 = [
        {'id': 'ce_2', 'source': 'CityExpert', 'title': 'Test2', 'price': 400, 'area_name': 'Novi Beograd', 'structure': '1.0', 'size': 35, 'publisher': '中介', 'url': 'http://c'},
        {'id': 'halo_2', 'source': 'HaloOglasi', 'title': 'Test2', 'price': 420, 'area_name': 'Novi Beograd', 'structure': '1', 'size': 35, 'publisher': '个人', 'url': 'http://d'},
    ]
    result2 = _cross_platform_dedup_prefer(items_dup2)
    assert len(result2) == 1, f"Expected 1 after dedup, got {len(result2)}"
    assert result2[0]['publisher'] == '个人', "Should pick personal even if more expensive"
    tests_passed += 1
    print(f"  ✅ Test 7: cross-platform dedup personal priority wins")
    
    # Test 8: no dedup when fingerprints don't match
    tests_total += 1
    items_different = [
        {'id': 'a', 'source': 'CE', 'title': 'A', 'price': 500, 'area_name': 'Vračar', 'structure': '2', 'size': 50, 'publisher': '中介', 'url': 'http://a'},
        {'id': 'b', 'source': 'HO', 'title': 'B', 'price': 600, 'area_name': 'Zemun', 'structure': '2', 'size': 50, 'publisher': '中介', 'url': 'http://b'},
        {'id': 'c', 'source': '4Z', 'title': 'C', 'price': 550, 'area_name': 'Vračar', 'structure': '3', 'size': 50, 'publisher': '个人', 'url': 'http://c'},
    ]
    result3 = _cross_platform_dedup_prefer(items_different)
    assert len(result3) == 3, "All different items should be kept"
    tests_passed += 1
    print(f"  ✅ Test 8: no dedup when fingerprints differ")
    
    # Test 9: 4zida area detection
    tests_total += 1
    area = _detect_4zida_area_from_slug('/izdavanje-stanova/crveni-krst-vracar-vracar-beograd/trosoban-stan/6a995e')
    assert area == 'Vračar', f"Expected Vračar from slug, got {area}"
    tests_passed += 1
    print(f"  ✅ Test 9: 4zida area from slug")
    
    # Test 10: 4zida room inference from slug
    tests_total += 1
    rooms = _infer_rooms_from_4zida_slug('/izdavanje-stanova/kalenic-vracar-beograd/dvoiposoban-stan/6aca69904b35c6413d0d428f')
    assert rooms == 2.5, f"Expected 2.5 from dvoiposoban, got {rooms}"
    tests_passed += 1
    print(f"  ✅ Test 10: 4zida room inference dvoiposoban=2.5")
    
    # Test 11: items with missing size (size=0) still fingerprint on area/rooms
    tests_total += 1
    item_no_size = {'area_name': 'Vračar', 'structure': '2', 'size': None}
    fp_nosize = _make_fingerprint(item_no_size)
    # Two items both missing size, same area/rooms should match (size=0=0)
    item_no_size2 = {'area_name': 'Vračar', 'structure': '2', 'size': None}
    fp_nosize2 = _make_fingerprint(item_no_size2)
    assert _fingerprint_match(fp_nosize, fp_nosize2), "Both missing size should match"
    tests_passed += 1
    print(f"  ✅ Test 11: fingerprint when size is None (both=0)")
    
    print(f"\n🎯 自测完成: {tests_passed}/{tests_total} 通过")
    return tests_passed == tests_total


if __name__ == '__main__':
    import sys
    if '--test' in sys.argv:
        ok = _self_test()
        sys.exit(0 if ok else 1)
    main()
