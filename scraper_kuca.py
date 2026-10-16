# -*- coding: utf-8 -*-
import os, sys, re, json, time, math
import pathlib
import cloudscraper
from bs4 import BeautifulSoup
from datetime import datetime

from utils.area_normalizer import normalize_area, normalize_4zida_slug

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

try:
    from error_diagnostics import (
        clear_source, record_error,
        SOURCE_CITYEXPERT, SOURCE_HALOOGLASI, SOURCE_4ZIDA
    )
except ImportError:
    def clear_source(n): pass
    def record_error(n, e, ctx=""): pass
    SOURCE_CITYEXPERT = "CityExpert"
    SOURCE_HALOOGLASI = "HaloOglasi"
    SOURCE_4ZIDA = "4zida"

os.makedirs(DATA_DIR, exist_ok=True)

HISTORY_KUCA_FILE = os.path.join(DATA_DIR, "history_kuca.json")
PENDING_FILE = os.path.join(DATA_DIR, "kuca_temp.json")

ENABLE_KUCA_SCRAPER = True

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

MIN_PRICE = 500
MAX_PRICE = 1300
MAX_PAGES = 3
ENABLE_VISION_FILTER = False
MAX_PAGES_4ZIDA = 3

TODAY_STR_KUCA = datetime.now().strftime('%Y-%m-%d')

def load_history_kuca():
    if os.path.exists(HISTORY_KUCA_FILE):
        try:
            with open(HISTORY_KUCA_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict): return raw
            if isinstance(raw, list): return {str(k): TODAY_STR_KUCA for k in raw if k}
            return {}
        except Exception: return {}
    return {}

def save_history_kuca(hist):
    with open(HISTORY_KUCA_FILE, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)

def item_global_key(item):
    return (item.get('url') or '').strip() or (item.get('id') or '').strip()

def parse_price(raw_str):
    if not raw_str: return None
    nums = re.findall(r'\d+', str(raw_str).replace('.', '').replace(',', ''))
    if nums:
        try: return float("".join(nums))
        except: return None
    return None

def parse_halo_kuca_detail(scraper, href, card_title=""):
    detail_info = {'size': None, 'rooms': '1.0', 'area': 'Belgrade'}
    try:
        r = scraper.get(href, timeout=15)
        if r.status_code != 200: return detail_info
        
        html = r.text
        soup = BeautifulSoup(html, 'html.parser')
        detail_info['area'] = normalize_area(f"{card_title} {soup.get_text()}")

        m_kv = re.search(r'"kvadratura_d"\s*:\s*([\d.]+)', html)
        if m_kv:
            val = float(m_kv.group(1))
            if 20 <= val <= 3000: detail_info['size'] = val

        m_soba = re.search(r'"broj_soba_s"\s*:\s*"([\d.]+)"', html)
        if m_soba:
            rm_val = float(m_soba.group(1))
            if 1 <= rm_val <= 15: detail_info['rooms'] = int(rm_val) if rm_val.is_integer() else rm_val

        if not detail_info['size']:
            for el in soup.find_all(['span', 'div', 'li']):
                txt = el.get_text().strip()
                if txt.lower() == 'kvadratura':
                    parent = el.parent
                    if parent:
                        m = re.search(r'(\d+(?:\.\d+)?)', parent.get_text().replace(',', '.'))
                        if m:
                            val = float(m.group(1))
                            if 20 <= val <= 3000:
                                detail_info['size'] = val
                                break

        if not detail_info['size']:
            all_sz = re.findall(r'(\d{2,4}(?:\.\d+)?)\s*m[²2]', soup.get_text(), re.I)
            valid_sz = [float(s) for s in all_sz if 20 <= float(s) <= 3000]
            if valid_sz: detail_info['size'] = valid_sz[0]

        if detail_info['rooms'] == '1.0':
            room_val = None
            for el in soup.find_all(['span', 'div', 'li']):
                txt = el.get_text().strip()
                if 'broj soba' in txt.lower():
                    parent = el.parent
                    if parent:
                        match_nums = re.findall(r'\b(\d+(?:\.\d+)?)\b', parent.get_text().replace(',', '.'))
                        for num_str in match_nums:
                            f_val = float(num_str)
                            if 1 <= f_val <= 15:
                                room_val = f_val
                                break
                    if room_val: break
            if room_val: detail_info['rooms'] = int(room_val) if room_val.is_integer() else room_val

        if detail_info['rooms'] == '1.0':
            m_title = re.search(r'(\d+(?:\.\d+)?)\s*(?:sobn|sobe|soba)', f"{card_title} {soup.get_text()}", re.I)
            if m_title:
                f_val = float(m_title.group(1))
                if 1 <= f_val <= 15: detail_info['rooms'] = int(f_val) if f_val.is_integer() else f_val

    except Exception as e:
        print(f"⚠️ 解析独栋详情页异常 {href}: {e}")
    
    return detail_info

def fetch_halooglasi_kuca():
    items = []
    sc = cloudscraper.create_scraper()
    sc.headers.update(DEFAULT_HEADERS)
    
    for page in range(1, MAX_PAGES + 1):
        url = f"https://www.halooglasi.com/nekretnine/izdavanje-kuca/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}&page={page}"
        try:
            r = sc.get(url, timeout=25)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            cards = soup.select('.product-item')
            if not cards: break

            for card in cards:
                did = card.get('data-id', '')
                if not did or not did.isdigit(): continue
                a_el = card.select_one('.product-title a[href]') or card.select_one('a.a-images[href]')
                if not a_el: continue
                href = (a_el.get('href') or '').strip().split('?')[0]
                if '/izdavanje-kuca/' not in href or '/baneri/' in href: continue
                
                price = None
                price_container = card.select_one('.central-feature') or card.select_one('.price-item') or card
                price_spans = price_container.select('span[data-value]') or [price_container]
                for p_span in price_spans:
                    p_val = p_span.get('data-value') or p_span.get_text()
                    parsed = parse_price(p_val)
                    if parsed and parsed > 50:
                        price = parsed
                        break

                if price is None or not (MIN_PRICE <= price <= MAX_PRICE): continue

                title = a_el.get_text().strip()
                desc_el = card.select_one('.product-description, .text-description-list')
                desc = desc_el.get_text().strip() if desc_el else ""

                text_for_parking = f"{title} {desc}".lower()
                has_parking = bool(re.search(r'parking|garaž|garaz|garage|车位', text_for_parking))

                img_el = card.select_one('img[src*=slike], img[data-src*=slike]')
                photo = ""
                if img_el:
                    photo = img_el.get('src') or img_el.get('data-src') or ""
                    if photo.startswith("//"): photo = "https:" + photo

                if ENABLE_VISION_FILTER and not photo: continue

                pub_el = card.select_one('.basic-info span')
                pub_text = pub_el.get_text().strip() if pub_el else ""
                publisher = "个人" if "Vlasnik" in pub_text or "个人" in pub_text else "中介"

                detail_data = parse_halo_kuca_detail(sc, f"https://www.halooglasi.com{href}", card_title=title)
                time.sleep(0.4)

                items.append({
                    'id': f'halo_{did}',
                    'source': 'HaloOglasi',
                    'title': title,
                    'price': price,
                    'area_name': detail_data['area'],
                    'structure': str(detail_data['rooms']),
                    'size': detail_data['size'],
                    'image': photo,
                    'url': f"https://www.halooglasi.com{href}",
                    'parking': has_parking,
                    'publisher': publisher
                })
            time.sleep(1)
        except Exception as e:
            print(f"第 {page} 页抓取异常: {e}", file=sys.stderr)
            
    return items

def _infer_rooms_from_4zida_slug(url):
    room_map = {
        'jednosoban': 1, 'dvosoban': 2, 'dvoiposoban': 2.5,
        'trosoban': 3, 'cetvorosoban': 4, 'petosoban': 5, 'sestosoban': 6,
    }
    m = re.search(r'/(jednosoban|dvosoban|dvoiposoban|trosoban|cetvorosoban|petosoban|sestosoban)-kuc', url.lower())
    if m: return room_map.get(m.group(1))
    m2 = re.search(r'/(jednosoban|dvosoban|dvoiposoban|trosoban|cetvorosoban|petosoban|sestosoban)-stan/', url.lower())
    return room_map.get(m2.group(1)) if m2 else None

def _extract_4zida_itemlist(html):
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    for s in scripts:
        if 'RealEstateListing' not in s or 'numberOfRooms' not in s: continue
        m = re.search(r'push\(\[.*?,"(\{.*?\})"\]\)', s, re.S)
        if not m: continue
        raw = m.group(1).replace('\\"', '"').replace('\\\\', '\\')
        try:
            data = json.loads(raw)
            main = data.get('mainEntity', data)
            if isinstance(main, dict) and 'itemListElement' in main: return main
            if isinstance(data, dict) and 'itemListElement' in data: return data
        except (json.JSONDecodeError, TypeError): continue
    return None

def _fetch_4zida_publisher(scraper, listing_url):
    try:
        r = scraper.get(listing_url, timeout=15)
        if r.status_code != 200: return '中介'
        html = r.text
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
        for s in scripts:
            if '#seller' not in s: continue
            if s.startswith('{'):
                try:
                    data = json.loads(s)
                    if data.get('@type') == 'Person': return '个人'
                    elif data.get('@type') == 'Organization': return '中介'
                except json.JSONDecodeError: pass
            m = re.search(r'push\(\[.*?,"(\{.*?\})"\]\)', s, re.S)
            if m:
                raw = m.group(1).replace('\\"', '"').replace('\\\\', '\\')
                try:
                    data = json.loads(raw)
                    if data.get('@type') == 'Person': return '个人'
                    elif data.get('@type') == 'Organization': return '中介'
                except (json.JSONDecodeError, TypeError): continue
        return '中介'
    except Exception: return '中介'

def fetch_4zida_kuca():
    items = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(DEFAULT_HEADERS)
    
    url = f"https://www.4zida.rs/izdavanje-kuca/beograd?cena_do={MAX_PRICE}&cena_od={MIN_PRICE}"
    
    for page in range(1, MAX_PAGES_4ZIDA + 1):
        page_url = url if page == 1 else f"{url}&stranica={page}"
        try:
            r = scraper.get(page_url, timeout=20)
            if r.status_code != 200: break
            
            html = r.text
            data = _extract_4zida_itemlist(html)
            if not data: break
            
            listings = data.get('itemListElement', [])
            if not listings: break
            
            for li in listings:
                item_data = li.get('item', {})
                li_url = li.get('url', '')
                
                ad_id_match = re.search(r'/([a-f0-9]{24})(?:/|$|\?)', li_url)
                if not ad_id_match: continue
                ad_id = ad_id_match.group(1)
                
                offers = item_data.get('offers', {})
                price = parse_price(offers.get('price')) if isinstance(offers, dict) else None
                if price is None or not (MIN_PRICE <= price <= MAX_PRICE): continue
                
                name = item_data.get('name', '').strip()
                item_offered = item_data.get('itemOffered', {})
                if isinstance(item_offered, dict):
                    rooms_raw = item_offered.get('numberOfRooms')
                    floor_size = item_offered.get('floorSize', {})
                    size = floor_size.get('value') if isinstance(floor_size, dict) else None
                else:
                    rooms_raw, size = None, None
                
                if not rooms_raw: rooms_raw = _infer_rooms_from_4zida_slug(li_url)
                
                area_name = normalize_4zida_slug(li_url)
                
                img_obj = item_data.get('image', {})
                img_url = img_obj.get('url', '') if isinstance(img_obj, dict) else ''
                if img_url and img_url.startswith('//'): img_url = 'https:' + img_url
                
                publisher = _fetch_4zida_publisher(scraper, li_url)
                time.sleep(0.3)
                
                try: size_int = int(size) if size else None
                except (ValueError, TypeError): size_int = None
                
                items.append({
                    'id': f"4z_{ad_id}",
                    'source': '4zida.rs',
                    'title': f"{name} · 独栋出租",
                    'price': price,
                    'area_name': area_name,
                    'structure': str(rooms_raw) if rooms_raw else '1.0',
                    'size': size_int,
                    'image': img_url or "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=800&q=80",
                    'url': li_url,
                    'parking': True,
                    'publisher': publisher
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"4zida.rs 独栋第 {page} 页抓取失败: {e}")
    
    return items

SIZE_TOLERANCE = 2

def _make_fingerprint(item):
    area = (item.get('area_name') or item.get('area') or '').strip().lower()
    rooms = item.get('structure') or item.get('rooms') or '1.0'
    try:
        rooms_f = float(rooms)
        rooms_norm = str(int(rooms_f)) if rooms_f.is_integer() else str(rooms_f)
    except (ValueError, TypeError): rooms_norm = '1'
    
    size = item.get('size')
    try: size_rounded = round(float(size)) if size else 0
    except (ValueError, TypeError): size_rounded = 0
    return f"{area}|{rooms_norm}|{size_rounded}"

def _fingerprint_match(fp1, fp2):
    parts1 = fp1.rsplit('|', 2)
    parts2 = fp2.rsplit('|', 2)
    if len(parts1) != 3 or len(parts2) != 3: return fp1 == fp2
    area1, rooms1, size1_str = parts1
    area2, rooms2, size2_str = parts2
    if area1 != area2 or rooms1 != rooms2: return False
    try:
        size1, size2 = int(size1_str), int(size2_str)
        if size1 == 0 or size2 == 0: return size1 == size2
        return abs(size1 - size2) <= SIZE_TOLERANCE
    except ValueError: return size1_str == size2_str

def _cross_platform_dedup_prefer(all_items):
    groups = {}
    for item in all_items:
        fp = _make_fingerprint(item)
        if fp not in groups: groups[fp] = []
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
        print(f"🔄 跨平台去重合并 {merged_count} 条重复房源（优选规则：价低优先 > 个人优先）")
    return preferred

def main():
    if not ENABLE_KUCA_SCRAPER: return

    print("\n📥 [1/2] HaloOglasi 独栋抓取中...")
    try:
        halo_items = fetch_halooglasi_kuca()
        print(f"   ✅ HaloOglasi: {len(halo_items)} 条")
        clear_source(SOURCE_HALOOGLASI)
    except Exception as e:
        print(f"   ❌ HaloOglasi 独栋抓取异常: {e}")
        record_error(SOURCE_HALOOGLASI, e, "fetch_halooglasi_kuca")
        halo_items = []
    
    print("\n📥 [2/2] 4zida.rs 独栋抓取中...")
    try:
        zida_items = fetch_4zida_kuca()
        print(f"   ✅ 4zida.rs: {len(zida_items)} 条")
        clear_source(SOURCE_4ZIDA)
    except Exception as e:
        print(f"   ❌ 4zida.rs 独栋抓取异常: {e}")
        record_error(SOURCE_4ZIDA, e, "fetch_4zida_kuca")
        zida_items = []
    
    all_items = halo_items + zida_items
    print(f"\n🔗 两源合计: {len(all_items)} 条，开始跨平台指纹去重...")
    preferred = _cross_platform_dedup_prefer(all_items)
    print(f"   ✅ 优选后: {len(preferred)} 条")
    
    history = load_history_kuca()
    new_items = []
    today_new_count = 0
    
    for item in preferred:
        k = item_global_key(item)
        if not k: continue
        prev_date = history.get(k) or history.get(item['id'])
        if prev_date is None:
            history[k] = TODAY_STR_KUCA
            if item['id'] and item['id'] != k:
                history[item['id']] = TODAY_STR_KUCA
            new_items.append(item)
            today_new_count += 1
        elif prev_date == TODAY_STR_KUCA:
            new_items.append(item)

    save_history_kuca(history)
    
    clean_items = [{k: v for k, v in item.items() if not k.startswith('_cross_')} for item in new_items]
    output_data = {
        "meta": {
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "sources": {"halooglasi": len(halo_items), "4zida": len(zida_items)}
        },
        "items": clean_items
    }
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 独栋抓取完成！两源合计 {len(all_items)} 条 → 优选 {len(preferred)} 条 → 输出 {len(new_items)} 套（其中全新 {today_new_count} 套）")

def _self_test():
    tests_passed = 0
    tests_total = 0
    
    tests_total += 1
    i1 = {'area_name': 'Zemun', 'structure': '3', 'size': 120}
    i2 = {'area_name': 'Zemun', 'structure': '3', 'size': 121}
    assert _fingerprint_match(_make_fingerprint(i1), _make_fingerprint(i2))
    tests_passed += 1
    print(f"  ✅ Test 1: fingerprint match")
    
    print(f"\n🎯 scraper_kuca 自测完成: {tests_passed}/{tests_total} 通过")
    return tests_passed == tests_total

if __name__ == "__main__":
    if '--test' in sys.argv:
        ok = _self_test()
        sys.exit(0 if ok else 1)
    main()
