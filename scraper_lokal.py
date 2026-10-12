# -*- coding: utf-8 -*-
import os, sys, re, json, time, math
import pathlib
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_LOKAL_FILE = DATA_DIR / "history_lokal.json"
PENDING_FILE = DATA_DIR / "lokal_items.json"

ENABLE_LOKAL_SCRAPER = True

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

MIN_PRICE = 400
MAX_PRICE = 2000
MIN_SIZE = 20
MAX_SIZE = 300
REQUIRE_PARKING = False
MAX_PAGES = 3
MAX_PAGES_4ZIDA = 1

AREA_ZH = {
    "Novi Beograd": "新贝尔格莱德", "Zemun": "泽蒙", "Vračar": "弗拉查尔",
    "Stari grad": "老城区", "Savski venac": "萨夫斯基维纳茨", "Čukarica": "丘卡里察",
    "Voždovac": "沃日多瓦茨", "Zvezdara": "兹韦兹达拉", "Palilula": "帕利卢拉",
    "Dorćol": "多尔乔尔", "Centar": "市中心"
}

FOURZIDA_AREA_MAP = {
    "novi-beograd": "Novi Beograd",
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
}

TODAY_STR_LOKAL = datetime.now().strftime('%Y-%m-%d')

def load_history_lokal():
    if HISTORY_LOKAL_FILE.exists():
        try:
            raw = json.loads(HISTORY_LOKAL_FILE.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, list):
                return {str(k): TODAY_STR_LOKAL for k in raw if k}
            return {}
        except Exception:
            return {}
    return {}

def save_history_lokal(hist):
    HISTORY_LOKAL_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding='utf-8')

def parse_num(raw_str):
    if not raw_str: return None
    nums = re.findall(r'\d+(?:\.\d+)?', str(raw_str).replace(' ', '').replace(',', '.'))
    if nums:
        try:
            return float(nums[0])
        except Exception:
            return None
    return None

def detect_area(blob):
    for en, zh in AREA_ZH.items():
        if en.lower() in blob.lower(): return en
    return "Belgrade"

def parse_halo_lokal_detail(scraper, href):
    detail = {'size': None}
    try:
        r = scraper.get(href, timeout=15)
        if r.status_code != 200:
            return detail
        
        html = r.text
        m_kv = re.search(r'"kvadratura_d"\s*:\s*([\d.]+)', html)
        if m_kv:
            val = float(m_kv.group(1))
            if 10 <= val <= 5000:
                detail['size'] = val

        if not detail['size']:
            soup = BeautifulSoup(html, 'html.parser')
            m_fallback = re.search(r'(\d+(?:\.\d+)?)\s*m[²2]', soup.get_text(), re.I)
            if m_fallback:
                val = float(m_fallback.group(1))
                if 10 <= val <= 5000:
                    detail['size'] = val
    except Exception as e:
        print(f"⚠️ 解析商铺详情页异常 {href}: {e}")
    return detail

def fetch_halooglasi_lokal():
    items = []
    sc = cloudscraper.create_scraper()
    sc.headers.update(DEFAULT_HEADERS)
    
    for page in range(1, MAX_PAGES + 1):
        url = (
            f"https://www.halooglasi.com/nekretnine/izdavanje-lokala/beograd"
            f"?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}"
            f"&kvadratura_od_m2={MIN_SIZE}&kvadratura_d_m2={MAX_SIZE}&page={page}"
        )
        try:
            r = sc.get(url, timeout=25)
            if r.status_code != 200: 
                break
                
            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.select('.product-item')
            if not cards: break

            for card in cards:
                did = card.get('data-id', '')
                if not did or not did.isdigit(): continue
                
                a_el = card.select_one('.product-title a[href]') or card.select_one('a.a-images[href]')
                if not a_el: continue
                href = (a_el.get('href') or '').strip().split('?')[0]
                
                price = None
                price_container = card.select_one('.central-feature') or card.select_one('.price-item') or card
                price_spans = price_container.select('span[data-value]') or [price_container]
                for p_span in price_spans:
                    p_val = p_span.get('data-value') or p_span.get_text()
                    parsed = parse_num(p_val)
                    if parsed and parsed > 50:
                        price = parsed
                        break

                if price is None or not (MIN_PRICE <= price <= MAX_PRICE): 
                    continue

                title = a_el.get_text().strip()
                desc_el = card.select_one('.product-description, .text-description-list')
                desc = desc_el.get_text().strip() if desc_el else ""
                places_ul = card.select_one('ul.subtitle-places')
                places_str = " ".join([li.get_text().strip() for li in places_ul.select('li')]) if places_ul else ""

                detail_url = f"https://www.halooglasi.com{href}"
                detail_data = parse_halo_lokal_detail(sc, detail_url)
                time.sleep(0.4)

                size = detail_data.get('size')
                if size and (size < MIN_SIZE or size > MAX_SIZE):
                    continue

                if size is None:
                    for li in card.select('ul.product-features li'):
                        txt = li.get_text()
                        if 'm2' in txt or 'm²' in txt:
                            size = parse_num(txt)
                            break
                    if size and (size < MIN_SIZE or size > MAX_SIZE):
                        continue

                text_blob = f"{title} {desc} {places_str}".lower()
                has_parking = bool(re.search(r'parking|garaž|garaz|garage|车位', text_blob))
                is_prizemlje = bool(re.search(r'prizemlje|izlog|沿街|临街|橱窗|一楼', text_blob))

                if REQUIRE_PARKING and not has_parking:
                    continue

                img_el = card.select_one('img[src*=slike], img[data-src*=slike]')
                photo = ""
                if img_el:
                    photo = img_el.get('src') or img_el.get('data-src') or ""
                    if photo.startswith("//"): photo = "https:" + photo

                items.append({
                    'id': f'halo_lokal_{did}',
                    'source': 'HaloOglasi',
                    'title': title,
                    'price': price,
                    'area_name': detect_area(f"{places_str} {desc}"),
                    'size': size,
                    'rooms': None,
                    'image': photo,
                    'photo': photo,
                    'url': f"https://www.halooglasi.com{href}",
                    'parking': has_parking,
                    'is_street_level': is_prizemlje,
                    'publisher': "中介"
                })
            time.sleep(1)
        except Exception as e:
            print(f"商铺第 {page} 页抓取异常: {e}", file=sys.stderr)
            
    return items

def _detect_4zida_area_from_slug(url_slug):
    slug = url_slug.lower()
    for slug_key, area_en in FOURZIDA_AREA_MAP.items():
        if slug_key in slug:
            return area_en
    return "Belgrade"

def _extract_4zida_itemlist(html):
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    for s in scripts:
        if 'RealEstateListing' not in s:
            continue
        m = re.search(r'push\(\[.*?,"(\{.*?\})"\]\)', s, re.S)
        if not m:
            continue
        raw = m.group(1).replace('\\"', '"').replace('\\\\', '\\')
        try:
            data = json.loads(raw)
            main = data.get('mainEntity', data)
            if isinstance(main, dict) and 'itemListElement' in main:
                return main
            if isinstance(data, dict) and 'itemListElement' in data:
                return data
        except (json.JSONDecodeError, TypeError):
            continue
    return None

def _fetch_4zida_publisher(scraper, listing_url):
    try:
        r = scraper.get(listing_url, timeout=15)
        if r.status_code != 200:
            return '中介'
        html = r.text
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        for s in scripts:
            if '#seller' not in s:
                continue
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
    except Exception:
        return '中介'

def fetch_4zida_lokal():
    items = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(DEFAULT_HEADERS)
    
    url = f"https://www.4zida.rs/izdavanje-lokala/beograd?cena_do={MAX_PRICE}&cena_od={MIN_PRICE}"
    
    for page in range(1, MAX_PAGES_4ZIDA + 1):
        page_url = url if page == 1 else f"{url}&stranica={page}"
        try:
            r = scraper.get(page_url, timeout=20)
            if r.status_code != 200:
                break
            
            html = r.text
            data = _extract_4zida_itemlist(html)
            if not data:
                break
            
            listings = data.get('itemListElement', [])
            if not listings:
                break
            
            for li in listings:
                item_data = li.get('item', {})
                li_url = li.get('url', '')
                
                ad_id_match = re.search(r'/([a-f0-9]{24})(?:/|$|\?)', li_url)
                if not ad_id_match:
                    continue
                ad_id = ad_id_match.group(1)
                
                offers = item_data.get('offers', {})
                price = parse_num(offers.get('price')) if isinstance(offers, dict) else None
                if price is None or not (MIN_PRICE <= price <= MAX_PRICE):
                    continue
                
                name = item_data.get('name', '').strip()
                item_offered = item_data.get('itemOffered', {})
                if isinstance(item_offered, dict):
                    floor_size = item_offered.get('floorSize', {})
                    size = floor_size.get('value') if isinstance(floor_size, dict) else None
                else:
                    size = None
                
                try:
                    size_val = float(size) if size else None
                except (ValueError, TypeError):
                    size_val = None
                
                if size_val and (size_val < MIN_SIZE or size_val > MAX_SIZE):
                    continue
                
                area_name = _detect_4zida_area_from_slug(li_url)
                
                img_obj = item_data.get('image', {})
                img_url = img_obj.get('url', '') if isinstance(img_obj, dict) else ''
                if img_url and img_url.startswith('//'):
                    img_url = 'https:' + img_url
                
                publisher = _fetch_4zida_publisher(scraper, li_url)
                time.sleep(0.3)
                
                items.append({
                    'id': f"4z_lokal_{ad_id}",
                    'source': '4zida.rs',
                    'title': f"{name} · 商铺出租",
                    'price': price,
                    'area_name': area_name,
                    'size': size_val,
                    'rooms': None,
                    'image': img_url or "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=800&q=80",
                    'photo': img_url or "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=800&q=80",
                    'url': li_url,
                    'parking': False,
                    'is_street_level': True,
                    'publisher': publisher
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"4zida.rs 商铺第 {page} 页抓取失败: {e}")
            
    return items

SIZE_TOLERANCE = 2

def _make_fingerprint(item):
    area = (item.get('area_name') or item.get('area') or '').strip().lower()
    size = item.get('size')
    try:
        size_rounded = round(float(size)) if size is not None else 0
    except (ValueError, TypeError):
        size_rounded = 0
    return f"{area}|lokal|{size_rounded}"

def _fingerprint_match(fp1, fp2):
    parts1 = fp1.rsplit('|', 2)
    parts2 = fp2.rsplit('|', 2)
    if len(parts1) != 3 or len(parts2) != 3:
        return fp1 == fp2
    area1, _, size1_str = parts1
    area2, _, size2_str = parts2
    if area1 != area2:
        return False
    try:
        size1, size2 = int(size1_str), int(size2_str)
        if size1 == 0 or size2 == 0:
            return size1 == size2
        return abs(size1 - size2) <= SIZE_TOLERANCE
    except ValueError:
        return size1_str == size2_str

def _cross_platform_dedup_prefer(all_items):
    groups = {}
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
        
        merged_count += len(candidates) - 1
        min_price = min(c['price'] for c in candidates)
        cheapest = [c for c in candidates if c['price'] == min_price]
        personal = [c for c in cheapest if c.get('publisher') == '个人']
        chosen = personal[0] if personal else cheapest[0]
        chosen['_cross_merged_from'] = [c['source'] for c in candidates]
        chosen['_cross_merged_count'] = len(candidates)
        preferred.append(chosen)
    
    if merged_count > 0:
        print(f"🔄 跨平台去重合并 {merged_count} 条重复商铺（优选规则：价低优先 > 个人优先）")
    return preferred

def main():
    if not ENABLE_LOKAL_SCRAPER:
        print("🚫 商铺爬虫已停用。")
        output_data = {"meta": {"min_price": MIN_PRICE, "max_price": MAX_PRICE}, "items": []}
        PENDING_FILE.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding='utf-8')
        return

    print("\n📥 [1/2] HaloOglasi 商铺抓取中...")
    halo_items = fetch_halooglasi_lokal()
    print(f"   ✅ HaloOglasi 商铺: {len(halo_items)} 条")

    print("\n📥 [2/2] 4zida.rs 商铺抓取中...")
    zida_items = fetch_4zida_lokal()
    print(f"   ✅ 4zida.rs 商铺: {len(zida_items)} 条")

    all_items = halo_items + zida_items
    print(f"\n🔗 双源合计: {len(all_items)} 条，开始跨平台指纹去重...")
    preferred = _cross_platform_dedup_prefer(all_items)
    print(f"   ✅ 优选后: {len(preferred)} 条")

    history = load_history_lokal()
    new_items = []
    today_new_count = 0
    
    for item in preferred:
        k = item.get('url') or item.get('id')
        if not k:
            continue

        prev_date = history.get(k)
        if prev_date is None:
            prev_date = history.get(item.get('id'))

        if prev_date is None:
            history[k] = TODAY_STR_LOKAL
            if item.get('id') and item.get('id') != k:
                history[item.get('id')] = TODAY_STR_LOKAL
            new_items.append(item)
            today_new_count += 1
        elif prev_date == TODAY_STR_LOKAL:
            new_items.append(item)

    save_history_lokal(history)

    clean_items = [{k: v for k, v in item.items() if not k.startswith('_cross_')} for item in new_items]

    output_data = {
        "meta": {
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "sources": {"halooglasi": len(halo_items), "4zida": len(zida_items)}
        },
        "items": clean_items
    }
    PENDING_FILE.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ 商铺抓取完成！双源合计 {len(all_items)} 条 → 优选 {len(preferred)} 条 → 输出 {len(new_items)} 条（其中全新 {today_new_count} 条）。")

def _self_test():
    tests_passed = 0
    tests_total = 0
    
    tests_total += 1
    i1 = {'area_name': 'Vračar', 'size': 100}
    i2 = {'area_name': 'Vračar', 'size': 101}
    assert _fingerprint_match(_make_fingerprint(i1), _make_fingerprint(i2))
    tests_passed += 1
    print(f"  ✅ Test 1: lokal fingerprint match (±1m²)")
    
    tests_total += 1
    i3 = {'area_name': 'Zemun', 'size': 100}
    assert not _fingerprint_match(_make_fingerprint(i1), _make_fingerprint(i3))
    tests_passed += 1
    print(f"  ✅ Test 2: different area = no match")
    
    tests_total += 1
    dup = [
        {'id': 'a', 'source': 'HO', 'title': 'L1', 'price': 800, 'area_name': 'Vračar', 'size': 80, 'publisher': '中介', 'url': 'http://a'},
        {'id': 'b', 'source': '4Z', 'title': 'L1', 'price': 750, 'area_name': 'Vračar', 'size': 80, 'publisher': '中介', 'url': 'http://b'},
    ]
    result = _cross_platform_dedup_prefer(dup)
    assert len(result) == 1 and result[0]['price'] == 750
    tests_passed += 1
    print(f"  ✅ Test 3: lokal dedup price priority")
    
    print(f"\n🎯 自测完成: {tests_passed}/{tests_total} 通过")
    return tests_passed == tests_total

if __name__ == "__main__":
    if '--test' in sys.argv:
        ok = _self_test()
        sys.exit(0 if ok else 1)
    main()
