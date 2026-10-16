# -*- coding: utf-8 -*-
import os, sys, json, re, time, math
import pathlib
from datetime import datetime
import cloudscraper
from bs4 import BeautifulSoup

from utils.area_normalizer import normalize_area, normalize_4zida_slug

try:
    from send_wechat import push_all, WECHAT_TARGETS
except ImportError:
    def push_all(text=None, items=None):
        print(f"📱 [微信推送] {text or items}")
        return True
    WECHAT_TARGETS = ["default"]

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

BASE_DIR = pathlib.Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_FILE = DATA_DIR / 'history_stan.json'
NEW_ITEMS_FILE = DATA_DIR / 'stan_temp.json'

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
MAX_PAGES_4ZIDA = 3

def load_history():
    if HISTORY_FILE.exists():
        try:
            raw = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
            if isinstance(raw, dict):
                return raw
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
                'area_name': normalize_area(item.get('municipality') or 'Belgrade'),
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
    detail_info = {'size': None, 'rooms': '1.0', 'area_name': 'Belgrade'}
    try:
        r = scraper.get(href, timeout=15)
        if r.status_code != 200:
            return detail_info
        
        html = r.text
        soup = BeautifulSoup(html, 'html.parser')
        full_text = soup.get_text()

        detail_info['area_name'] = normalize_area(f"{card_title} {full_text}")

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

        if not detail_info['size']:
            all_sz = re.findall(r'(\d{2,3}(?:\.\d+)?)\s*m[²2]', full_text, re.I)
            valid_sz = [float(s) for s in all_sz if 10 <= float(s) <= 500]
            if valid_sz:
                detail_info['size'] = valid_sz[0]

        if detail_info['rooms'] == '1.0':
            for row in soup.select('tr, li, div.detail-row'):
                row_text = row.get_text().lower()
                if 'soba' in row_text or 'sobe' in row_text:
                    m_rm = re.search(r'(\d+(?:\.\d+)?)', row_text)
                    if m_rm:
                        detail_info['rooms'] = m_rm.group(1)
                        break

        if detail_info['rooms'] == '1.0':
            m_rm_title = re.search(r'(\d+\.\d+|\d)\s*sobn', f"{card_title} {full_text}", re.I)
            if m_rm_title:
                detail_info['rooms'] = m_rm_title.group(1)

    except Exception as e:
        print(f"⚠️ 解析详情页异常 {href}: {e}")
    
    return detail_info

def fetch_4zida():
    items = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(DEFAULT_HEADERS)
    
    url = f"https://www.4zida.rs/izdavanje-stanova/beograd?cena_do={MAX_PRICE}&cena_od={MIN_PRICE}"
    
    for page in range(1, MAX_PAGES_4ZIDA + 1):
        page_url = url if page == 1 else f"{url}&stranica={page}"
        try:
            print(f"🔎 4zida.rs 第 {page}/{MAX_PAGES_4ZIDA} 页...")
            r = scraper.get(page_url, timeout=20)
            if r.status_code != 200:
                break
            
            html = r.text
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
                
                ad_id_match = re.search(r'/([a-f0-9]{24})(?:/|$|\?)', li_url)
                if not ad_id_match:
                    continue
                ad_id = ad_id_match.group(1)
                
                offers = item_data.get('offers', {})
                price = parse_price(offers.get('price')) if isinstance(offers, dict) else None
                if not within_budget(price):
                    continue
                
                name = item_data.get('name', '').strip()
                
                item_offered = item_data.get('itemOffered', {})
                if isinstance(item_offered, dict):
                    rooms_raw = item_offered.get('numberOfRooms')
                    floor_size = item_offered.get('floorSize', {})
                    size = floor_size.get('value') if isinstance(floor_size, dict) else None
                else:
                    rooms_raw, size = None, None
                
                if not rooms_raw:
                    rooms_raw = _infer_rooms_from_4zida_slug(li_url)
                rooms = str(rooms_raw) if rooms_raw else '1.0'
                
                area_name = normalize_4zida_slug(li_url)
                
                img_obj = item_data.get('image', {})
                img_url = img_obj.get('url', '') if isinstance(img_obj, dict) else ''
                if img_url and img_url.startswith('//'):
                    img_url = 'https:' + img_url
                
                publisher = _fetch_4zida_publisher(scraper, li_url)
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
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.S)
    for s in scripts:
        if 'RealEstateListing' not in s or 'numberOfRooms' not in s:
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

def _infer_rooms_from_4zida_slug(url):
    room_map = {
        'jednosoban': 1, 'dvosoban': 2, 'dvoiposoban': 2.5,
        'trosoban': 3, 'cetvorosoban': 4, 'petosoban': 5, 'sestosoban': 6,
    }
    m = re.search(r'/(jednosoban|dvosoban|dvoiposoban|trosoban|cetvorosoban|petosoban|sestosoban)-stan/', url.lower())
    return room_map.get(m.group(1)) if m else None

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
    except Exception:
        return '中介'

SIZE_TOLERANCE = 2

def _make_fingerprint(item):
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
    except ValueError:
        return size1_str == size2_str

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
        personal = [c for c in candidates if c.get('publisher') == '个人']
        chosen = min(personal, key=lambda c: c['price']) if personal else min(candidates, key=lambda c: c['price'])
        chosen['_cross_merged_from'] = [c['source'] for c in candidates]
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
    
    print("\n📥 [1/3] CityExpert 抓取中...")
    try:
        ce_items = fetch_cityexpert()
        print(f"   ✅ CityExpert: {len(ce_items)} 条")
        clear_source(SOURCE_CITYEXPERT)
    except Exception as e:
        print(f"   ❌ CityExpert 抓取异常: {e}")
        record_error(SOURCE_CITYEXPERT, e, "fetch_cityexpert")
        ce_items = []
    
    print("\n📥 [2/3] HaloOglasi 抓取中...")
    try:
        halo_items = fetch_halooglasi()
        print(f"   ✅ HaloOglasi: {len(halo_items)} 条")
        clear_source(SOURCE_HALOOGLASI)
    except Exception as e:
        print(f"   ❌ HaloOglasi 抓取异常: {e}")
        record_error(SOURCE_HALOOGLASI, e, "fetch_halooglasi")
        halo_items = []
    
    print("\n📥 [3/3] 4zida.rs 抓取中...")
    try:
        zida_items = fetch_4zida()
        print(f"   ✅ 4zida.rs: {len(zida_items)} 条")
        clear_source(SOURCE_4ZIDA)
    except Exception as e:
        print(f"   ❌ 4zida.rs 抓取异常: {e}")
        record_error(SOURCE_4ZIDA, e, "fetch_4zida")
        zida_items = []
    
    all_items = ce_items + halo_items + zida_items
    print(f"\n🔗 三源合计: {len(all_items)} 条，开始跨平台指纹去重...")
    preferred = _cross_platform_dedup_prefer(all_items)
    print(f"   ✅ 优选后: {len(preferred)} 条")
    
    history = load_history()
    new_items = []
    today_new_count = 0
    
    for item in preferred:
        k = item_key(item)
        if not k: continue
        prev_date = history.get(k) or history.get(item['id'])
        if prev_date is None:
            history[k] = TODAY_STR
            if item['id'] and item['id'] != k:
                history[item['id']] = TODAY_STR
            new_items.append(item)
            today_new_count += 1
        elif prev_date == TODAY_STR:
            new_items.append(item)
    
    save_history(history)
    
    clean_items = [{k: v for k, v in item.items() if not k.startswith('_cross_')} for item in new_items]
    output_data = {
        "meta": {
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "sources": {"cityexpert": len(ce_items), "halooglasi": len(halo_items), "4zida": len(zida_items)}
        },
        "items": clean_items
    }
    NEW_ITEMS_FILE.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n✅ 公寓抓取完成！三源合计 {len(all_items)} 条 → 优选 {len(preferred)} 条 → 输出 {len(new_items)} 套（其中全新 {today_new_count} 套）")

def _self_test():
    tests_passed = 0
    tests_total = 0
    
    tests_total += 1
    item1 = {'area_name': 'Vračar', 'structure': '3', 'size': 86}
    item2 = {'area_name': 'Vračar', 'structure': '3', 'size': 87}
    assert _fingerprint_match(_make_fingerprint(item1), _make_fingerprint(item2))
    tests_passed += 1
    print(f"  ✅ Test 1: fingerprint match")
    
    tests_total += 1
    area = normalize_4zida_slug('/izdavanje-stanova/crveni-krst-vracar-vracar-beograd/trosoban-stan/6a995e')
    assert area == 'Vračar'
    tests_passed += 1
    print(f"  ✅ Test 2: 4zida area from slug via normalizer")
    
    print(f"\n🎯 scraper_stan 自测完成: {tests_passed}/{tests_total} 通过")
    return tests_passed == tests_total

if __name__ == '__main__':
    if '--test' in sys.argv:
        ok = _self_test()
        sys.exit(0 if ok else 1)
    main()
