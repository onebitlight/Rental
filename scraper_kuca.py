# -*- coding: utf-8 -*-
import os, sys, re, json, time
import cloudscraper
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 全局历史去重文件：记录已见过的 property_id / url，跨日全量判重
HISTORY_KUCA_FILE = os.path.join(DATA_DIR, "history_kuca.json")
PENDING_FILE = os.path.join(DATA_DIR, "push_pending.json")

BASE_URL = "https://estate.onebitlight.xyz"  # 永久公网域名（Cloudflare Zero Trust Tunnel），根映射 /Volumes/Data2TB/rent/

# 🎛️ 多业态开关：ENABLE_KUCA_SCRAPER = True 表示启用独栋爬虫
# False 时入口会清空 push_pending.json 并直接退出（不抓取、不推送）
ENABLE_KUCA_SCRAPER = True


def load_history_kuca():
    if os.path.exists(HISTORY_KUCA_FILE):
        try:
            with open(HISTORY_KUCA_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_history_kuca(hist):
    with open(HISTORY_KUCA_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(hist), f, ensure_ascii=False, indent=2)

def item_global_key(item):
    """全局去重键：优先用完整 url，其次用 id（property_id）。"""
    return (item.get('url') or '').strip() or (item.get('id') or '').strip()

# ==============================================
# 🎛️ 独栋抓取核心配置项（可在此自由调整）
# ==============================================
MIN_PRICE = 500             # 期望最低价格 (EUR)
MAX_PRICE = 1300            # 期望最高价格 (EUR)
MAX_PAGES = 3               # 抓取页数（防止便宜/远郊房源被挤到后几页）
ENABLE_VISION_FILTER = False # 👁️ 视觉/图片质量严格筛选开关 (True=开启严格筛选, False=不过滤放行)

AREA_ZH = {
    "Novi Beograd": "新贝尔格莱德", "Zemun": "泽蒙", "Vračar": "弗拉查尔",
    "Stari grad": "老城区", "Savski venac": "萨夫斯基维纳茨", "Čukarica": "丘卡里察",
    "Voždovac": "沃日多瓦茨", "Zvezdara": "兹韦兹达拉", "Palilula": "帕利卢拉",
    "Rakovica": "拉科维察", "Surčin": "苏尔钦", "Dedinje": "德丁耶", "Senjak": "森亚克"
}

def parse_price(raw_str):
    if not raw_str: return None
    nums = re.findall(r'\d+', str(raw_str).replace('.', '').replace(',', ''))
    if nums:
        try:
            return float("".join(nums))
        except:
            return None
    return None

def detect_area(blob):
    for en, zh in AREA_ZH.items():
        if en.lower() in blob.lower(): return en
    return "Belgrade"

def fetch_halooglasi_kuca():
    items = []
    sc = cloudscraper.create_scraper()
    
    # 支持多页翻页抓取
    for page in range(1, MAX_PAGES + 1):
        url = f"https://www.halooglasi.com/nekretnine/izdavanje-kuca/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}&page={page}"
        try:
            print(f"🔎 正在抓取独栋房源 第 {page}/{MAX_PAGES} 页...")
            r = sc.get(url, timeout=25)
            if r.status_code != 200: 
                print(f"HTTP 请求异常: {r.status_code}")
                break
                
            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.select('.product-item')
            if not cards:
                break

            for card in cards:
                did = card.get('data-id', '')
                if not did or not did.isdigit(): continue
                
                a_el = card.select_one('.product-title a[href]') or card.select_one('a.a-images[href]')
                if not a_el: continue
                href = (a_el.get('href') or '').strip().split('?')[0]
                if '/izdavanje-kuca/' not in href or '/baneri/' in href: continue
                
                # 精准价格提取
                price = None
                price_container = card.select_one('.central-feature') or card.select_one('.price-item') or card
                price_spans = price_container.select('span[data-value]') or [price_container]
                for p_span in price_spans:
                    p_val = p_span.get('data-value') or p_span.get_text()
                    parsed = parse_price(p_val)
                    if parsed and parsed > 50:
                        price = parsed
                        break

                # 严格价格过滤：超出区间直接丢弃
                if price is None or not (MIN_PRICE <= price <= MAX_PRICE): 
                    continue

                title = a_el.get_text().strip()
                desc_el = card.select_one('.product-description, .text-description-list')
                desc = desc_el.get_text().strip() if desc_el else ""
                places_ul = card.select_one('ul.subtitle-places')
                places_str = " ".join([li.get_text().strip() for li in places_ul.select('li')]) if places_ul else ""

                text_for_parking = f"{title} {desc} {places_str}".lower()
                has_parking = bool(re.search(r'parking|garaž|garaz|garage|车位', text_for_parking))

                size, rooms = None, None
                for li in card.select('ul.product-features li'):
                    txt = li.get_text()
                    if 'm²' in txt: size = parse_price(txt)
                    elif 'soba' in txt.lower():
                        m = re.search(r'\d+(\.\d+)?', txt)
                        if m: rooms = float(m.group())

                img_el = card.select_one('img[src*=slike], img[data-src*=slike]')
                photo = ""
                if img_el:
                    photo = img_el.get('src') or img_el.get('data-src') or ""
                    if photo.startswith("//"): photo = "https:" + photo

                # 如果开启了严格视觉/图片开关，且图片缺失，则跳过
                if ENABLE_VISION_FILTER and not photo:
                    continue

                pub_el = card.select_one('.basic-info span')
                pub_text = pub_el.get_text().strip() if pub_el else ""
                publisher = "个人" if "Vlasnik" in pub_text or "个人" in pub_text else "中介/机构"

                items.append({
                    'id': f'halo_{did}',
                    'source': 'HaloOglasi',
                    'title': title,
                    'street': title,
                    'price': price,
                    'area': detect_area(f"{places_str} {desc}"),
                    'size': size,
                    'rooms': rooms,
                    'photo': photo,
                    'url': f"https://www.halooglasi.com{href}",
                    'parking': has_parking,
                    'publisher': publisher
                })
            time.sleep(1) # 礼貌抓取间隔
        except Exception as e:
            print(f"第 {page} 页抓取异常: {e}", file=sys.stderr)
            
    return items

if __name__ == "__main__":
    # 🎛️ 多业态开关判断：独栋关闭时清空 pending 数据并直接退出
    if not ENABLE_KUCA_SCRAPER:
        print("🚫 独栋爬虫已停用 (ENABLE_KUCA_SCRAPER = False)，清空 push_pending.json 后退出。")
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        sys.exit(0)

    results = fetch_halooglasi_kuca()

    # 全局去重：基于 history_kuca.json（id 与 url 都记录），仅保留真正新增
    history = load_history_kuca()
    new_items = []
    for item in results:
        k = item_global_key(item)
        if not k or k in history or item['id'] in history:
            continue
        new_items.append(item)

    # 把新增写入历史，供后续全量判重
    for item in new_items:
        history.add(item_global_key(item))
        history.add(item['id'])
    save_history_kuca(history)

    # push_pending.json 只保留真正新增（无新增则写空数组，避免重复推送历史房源）
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(new_items, f, ensure_ascii=False, indent=2)

    if new_items:
        print(f"✅ 独栋抓取完成！€{MIN_PRICE}-€{MAX_PRICE} 预算内共提取 {len(results)} 条，新增 {len(new_items)} 条（其余已在历史库中）。")
    else:
        print(f"📭 今日无新增独栋房源（抓取 {len(results)} 条均已在历史库中），push_pending.json 已置空。")
