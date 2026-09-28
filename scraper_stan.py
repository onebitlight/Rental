# -*- coding: utf-8 -*-
import os, sys, json, re, time
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

HISTORY_FILE = DATA_DIR / 'history.json'
NEW_ITEMS_FILE = DATA_DIR / 'new_items.json'

TODAY_STR = datetime.now().strftime('%Y-%m-%d')

EXTERNAL_RENT_DIR = pathlib.Path('/Volumes/Data2TB/rent')
if EXTERNAL_RENT_DIR.exists() and os.access(EXTERNAL_RENT_DIR, os.W_OK):
    OUTPUT_BASE = EXTERNAL_RENT_DIR
else:
    OUTPUT_BASE = BASE_DIR / 'output'

TODAY_OUTPUT_DIR = OUTPUT_BASE / f'stan_{TODAY_STR}'
TODAY_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 🎛️ 多业态开关：ENABLE_STAN_SCRAPER = False 表示公寓爬虫已主动停用
# False 时入口会置空 new_items.json 并跳过抓取（不抓取、不推送）
# ⚠️ AI Agent 维护时严禁将其设为 True（见 PROJECT_NOTES.md / AGENTS.md）
ENABLE_STAN_SCRAPER = False

# ==============================================
# 🎛️ 公寓抓取核心配置项
# ==============================================
MIN_PRICE = 350
MAX_PRICE = 650
MAX_PAGES = 3               # 多页抓取页数

def load_history():
    if HISTORY_FILE.exists():
        try:
            return set(json.loads(HISTORY_FILE.read_text(encoding='utf-8')))
        except:
            return set()
    return set()

def save_history(history_set):
    HISTORY_FILE.write_text(json.dumps(list(history_set), ensure_ascii=False, indent=2), encoding='utf-8')

def item_key(item):
    """全局去重键：优先用 url，其次用 id（property_id），保证跨源不重复。"""
    return item.get('url') or item.get('id') or ''

def parse_price(val):
    if val is None or isinstance(val, bool):
        return None
    try:
        s = str(val).replace('€', '').replace('EUR', '').replace('eur', '').strip()
        s = s.replace(',', '')
        m = re.search(r'\d+(\.\d+)?', s)
        if not m:
            return None
        p = round(float(m.group()))
        return p if p > 0 else None
    except Exception:
        return None

def within_budget(price):
    p = parse_price(price)
    return p is not None and MIN_PRICE <= p <= MAX_PRICE

def fetch_cityexpert():
    """1. CityExpert 专属提取逻辑"""
    items = []
    url = f"https://cityexpert.rs/en/properties-for-rent/belgrade?ptypeid=1&priceFrom={MIN_PRICE}&priceTo={MAX_PRICE}"
    try:
        scraper = cloudscraper.create_scraper()
        r = scraper.get(url, timeout=20)
        if r.status_code != 200:
            return items
        m = re.search(r'<script id="ng-state" type="application/json">(.*?)</script>', r.text, re.S)
        if not m:
            return items
        data = json.loads(m.group(1))

        def _find_results(obj):
            if isinstance(obj, dict):
                if 'result' in obj and isinstance(obj['result'], list):
                    return obj['result']
                for v in obj.values():
                    res = _find_results(v)
                    if res is not None:
                        return res
            return None

        response_data = _find_results(data) or []
        for item in response_data:
            prop_id = item.get('propId') or item.get('uniqueID')
            if not prop_id:
                continue
            price = parse_price(item.get('price'))
            if not within_budget(price):
                continue

            street = item.get('street') or 'Belgrade'
            structure = str(item.get('structure') or '1.0')
            cp = item.get('coverPhoto') or ''
            img_url = ""
            if cp:
                try:
                    bucket = int(int(prop_id) / 10000) * 10000
                except Exception:
                    bucket = 0
                img_url = f"https://img.cityexpert.rs/properties/470x/{bucket}/{prop_id}/slike/{cp}@avif"

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
                'area_name': item.get('municipality') or '贝尔格莱德',
                'structure': structure,
                'features': " · ".join(features_list),
                'size': size,
                'image': img_url,
                'parking': parking,
                'publisher': '中介/机构',
                'url': item_url
            })
    except Exception as e:
        print(f"CityExpert 抓取失败: {e}")
    return items

def fetch_halooglasi():
    """2. HaloOglasi 专属提取逻辑（支持多页翻页抓取）"""
    items = []
    scraper = cloudscraper.create_scraper()
    
    for page in range(1, MAX_PAGES + 1):
        url = f"https://www.halooglasi.com/nekretnine/izdavanje-stanova/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}&page={page}"
        try:
            r = scraper.get(url, timeout=20)
            if r.status_code != 200:
                break

            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.find_all('div', class_='product-item')
            if not cards:
                break

            for card in cards:
                item_id = card.get('data-id')
                if not item_id:
                    continue

                price = None
                price_span = card.find('span', attrs={'data-value': True})
                if price_span:
                    price = parse_price(price_span.get('data-value'))
                if not price:
                    price_i = card.select_one('.central-feature i')
                    if price_i:
                        price = parse_price(price_i.text)

                if not within_budget(price):
                    continue

                img_url = ""
                img_tag = card.find('img')
                if img_tag:
                    cand = img_tag.get('src') or img_tag.get('data-src') or ''
                    if cand.startswith('//'):
                        cand = 'https:' + cand
                    elif cand.startswith('/'):
                        cand = 'https://www.halooglasi.com' + cand

                    if 'slike/oglasi' in cand and 'no-image' not in cand:
                        img_url = cand

                link_tag = card.select_one('.product-title a')
                title = link_tag.text.strip() if link_tag else "贝尔格莱德精选公寓"
                href = link_tag.get('href', '') if link_tag else ''
                if href.startswith('/'):
                    href = 'https://www.halooglasi.com' + href

                subtitle = []
                places = card.select('ul.subtitle-places li')
                for p in places:
                    t = p.text.strip()
                    if t: subtitle.append(t)
                
                features_text = " · ".join(subtitle) if subtitle else "精选户型 · 随时入住"

                items.append({
                    'id': f"halo_{item_id}",
                    'source': 'HaloOglasi',
                    'title': title,
                    'price': price,
                    'area_name': '贝尔格莱德',
                    'structure': '精选户型',
                    'features': features_text,
                    'size': None,
                    'image': img_url or "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80",
                    'publisher': '中介/机构',
                    'url': href
                })
            time.sleep(1)
        except Exception as e:
            print(f"HaloOglasi 第 {page} 页抓取失败: {e}")
            
    return items

def main():
    # 🎛️ 多业态开关判断：公寓停用时置空 new_items.json 并跳过抓取
    if not ENABLE_STAN_SCRAPER:
        print("🚫 公寓爬虫已主动停用 (ENABLE_STAN_SCRAPER = False)，置空 new_items.json 并跳过抓取。")
        NEW_ITEMS_FILE.write_text(json.dumps([], ensure_ascii=False, indent=2), encoding='utf-8')
        return

    print(f"🚀 开始精准并发抓取贝尔格莱德公寓 (预算: €{MIN_PRICE} - €{MAX_PRICE})...")
    history = load_history()

    ce_items = fetch_cityexpert()
    halo_items = fetch_halooglasi()

    all_items = ce_items + halo_items

    # 全局去重：基于 history（id 与 url 都记录），仅保留真正新增
    new_items = []
    for item in all_items:
        k = item_key(item)
        if not k or k in history or item['id'] in history:
            continue
        new_items.append(item)

    print(f"📊 累计抓取房源: {len(all_items)} 套，新增: {len(new_items)} 套")

    for item in new_items:
        history.add(item_key(item))
        history.add(item['id'])

    save_history(history)
    NEW_ITEMS_FILE.write_text(json.dumps(new_items, ensure_ascii=False, indent=2), encoding='utf-8')

    if new_items:
        push_all(items=new_items, text=f"🏠 【公寓租房日报】今日新增 {len(new_items)} 套符合条件的公寓房源！")
    else:
        push_all(text="🏠 【公寓租房日报】今日无新增房源，暂无符合条件的公寓。")

if __name__ == '__main__':
    main()
