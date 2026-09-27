# -*- coding: utf-8 -*-
import os, sys, re, json
import cloudscraper
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

MIN_PRICE = 300
MAX_PRICE = 2000

AREA_ZH = {
    "Novi Beograd": "新贝尔格莱德", "Zemun": "泽蒙", "Vračar": "弗拉查尔",
    "Stari grad": "老城区", "Savski venac": "萨夫斯基维纳茨", "Čukarica": "丘卡里察",
    "Voždovac": "沃日多瓦茨", "Zvezdara": "兹韦兹达拉", "Palilula": "帕利卢拉",
    "Rakovica": "拉科维察", "Surčin": "苏尔钦", "Dedinje": "德丁耶", "Senjak": "森亚克"
}

def parse_price(raw_str):
    if not raw_str: return None
    # 只提取数字字符
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
    url = f"https://www.halooglasi.com/nekretnine/izdavanje-kuca/beograd?cena_d_eur={MAX_PRICE}&cena_od_eur={MIN_PRICE}"
    sc = cloudscraper.create_scraper()
    try:
        r = sc.get(url, timeout=25)
        if r.status_code != 200: 
            print(f"HTTP 请求异常: {r.status_code}")
            return items
            
        soup = BeautifulSoup(r.text, 'html.parser')
        cards = soup.select('.product-item')
        print(f"页面共扫到 {len(cards)} 个原始房源卡片卡位")

        for card in cards:
            did = card.get('data-id', '')
            if not did or not did.isdigit(): continue
            
            a_el = card.select_one('.product-title a[href]') or card.select_one('a.a-images[href]')
            if not a_el: continue
            href = (a_el.get('href') or '').strip().split('?')[0]
            if '/izdavanje-kuca/' not in href or '/baneri/' in href: continue
            
            # 价格提取逻辑强化
            price = None
            price_container = card.select_one('.central-feature') or card.select_one('.price-item') or card
            price_spans = price_container.select('span[data-value]') or [price_container]
            for p_span in price_spans:
                p_val = p_span.get('data-value') or p_span.get_text()
                parsed = parse_price(p_val)
                if parsed and parsed > 50:  # 排除非价格小数字
                    price = parsed
                    break

            # 调试提示：如果价格解析不到则跳过
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
    except Exception as e:
        print(f"抓取异常: {e}", file=sys.stderr)
    return items

if __name__ == "__main__":
    results = fetch_halooglasi_kuca()
    pending_file = os.path.join(BASE_DIR, "data", "push_pending.json")
    with open(pending_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"✅ 成功提取到 {len(results)} 条数据并保存到 {pending_file}")
