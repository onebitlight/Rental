#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
area_normalizer.py — 通用塞尔维亚语行政区归一化模块
====================================================

收编 Belgrade 17 个主行政区 + 次级街区映射 + 4zida 连字符 slug 映射。
处理塞尔维亚语名词变格（如 Voždovac → Voždovca/Voždovcu、Vračar → Vračara 等）。

使用方式:
    from utils.area_normalizer import normalize_area, normalize_4zida_slug

    normalize_area("Stan na Ledinama")               → "Surčin"
    normalize_area("Bulbulder Mehmeda Sokolovića")  → "Zvezdara"
    normalize_4zida_slug("novi-beograd")             → "Novi Beograd"
    normalize_4zida_slug("beograd-na-vodi")          → "Savski venac"
"""

import re
import unicodedata
from typing import Dict, Optional, Tuple


# ── 主行政区映射（标准英文名） ────────────────────────────

AREA_MAP: Dict[str, str] = {
    "novi beograd": "Novi Beograd",
    "stari grad": "Stari grad",
    "savski venac": "Savski venac",
    "banovo brdo": "Čukarica",
    "zemun": "Zemun",
    "vračar": "Vračar", "vracar": "Vračar",
    "čukarica": "Čukarica", "cukarica": "Čukarica",
    "voždovac": "Voždovac", "vozdovac": "Voždovac",
    "zvezdara": "Zvezdara",
    "palilula": "Palilula",
    "rakovica": "Rakovica",
    "surčin": "Surčin", "surcin": "Surčin",
    "dedinje": "Dedinje",
    "senjak": "Senjak",
    "dorćol": "Dorćol", "dorcol": "Dorćol",
}


# ── 4zida 连字符 Slug 映射 ──────────────────────────────

FOURZIDA_SLUG_MAP: Dict[str, str] = {
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


# ── 次级地名/街区 → 主行政区映射 ─────────────────────────

SUB_LOCALITY_MAP: Dict[str, str] = {
    "bulbulder": "Zvezdara",
    "lion": "Zvezdara",
    "cvetko": "Zvezdara",
    "cvetkova": "Zvezdara",
    "cvetkova pijaca": "Zvezdara",
    "crveni krst": "Vračar",
    "crvenog krsta": "Vračar",
    "kalenić": "Vračar",
    "kalenic": "Vračar",
    "kalenić pijaca": "Vračar",
    "ledine": "Surčin",
    "ledinama": "Surčin",
    "fontana": "Novi Beograd",
    "blok 70": "Novi Beograd",
    "blok 45": "Novi Beograd",
    "blok 21": "Novi Beograd",
    "blok 30": "Novi Beograd",
    "blok 11": "Novi Beograd",
    "karaburma": "Palilula",
    "mirijevo": "Zvezdara",
    "konjarnik": "Voždovac",
    "konjarnika": "Voždovac",
    "centar grada": "Stari grad",
    "kotež": "Palilula",
    "kotez": "Palilula",
    "borča": "Palilula",
    "borca": "Palilula",
    "krnjača": "Palilula",
    "krnjaca": "Palilula",
    "altina": "Zemun",
    "batajnica": "Zemun",
    "mali mokri lug": "Zvezdara",
    "veliki mokri lug": "Zvezdara",
    "bulevar kralja aleksandra": "Zvezdara",
    "labudovo brdo": "Rakovica",
    "miljakovac": "Rakovica",
    "kanarevo brdo": "Rakovica",
    "vidikovac": "Rakovica",
    "železnik": "Čukarica",
    "zeleznik": "Čukarica",
    "makiš": "Čukarica",
    "makis": "Čukarica",
    "beograd na vodi": "Savski venac",
    "beograd-na-vodi": "Savski venac",
    "savski kej": "Novi Beograd",
}


# ── 核心通用函数 ──────────────────────────────────────────

def _norm(text: str) -> str:
    """NFKD 规范化 + 去除组合字符。"""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _stem_at_least(key: str, min_len: int = 4) -> Optional[str]:
    """词干提取（兼容名词变格后缀）。"""
    if len(key) <= min_len:
        return key
    stem = key[:-2]
    if len(stem) < min_len:
        return key
    return stem


def _stem_match(stem: str, word: str) -> bool:
    """检查 stem 是否为 word 前缀。"""
    if not word.startswith(stem):
        return False
    remaining = word[len(stem):]
    return remaining == "" or remaining.isalpha()


def _match_area_from_map(candidates_text: str, area_map: Dict[str, str],
                          multi_word_keys: set,
                          single_word_exact_only: bool = False) -> Optional[Tuple[str, int]]:
    candidates: list = []
    tokens = candidates_text.split()

    for key, area_en in area_map.items():
        if key in multi_word_keys:
            idx = candidates_text.find(key)
            if idx >= 0:
                candidates.append((idx, len(key), key, area_en))
        else:
            match_pos = None
            if single_word_exact_only:
                for tok in tokens:
                    if tok == key:
                        match_pos = candidates_text.find(tok)
                        break
            else:
                stem = _stem_at_least(key, min_len=4)
                for tok in tokens:
                    if _stem_match(stem, tok):
                        match_pos = candidates_text.find(tok)
                        break

                if match_pos is None:
                    m = re.search(r"\b" + re.escape(key) + r"\w*\b", candidates_text)
                    if m:
                        match_pos = m.start()

            if match_pos is not None:
                candidates.append((match_pos, len(key), key, area_en))

    if candidates:
        candidates.sort(key=lambda c: (c[0], -c[1]))
        return (candidates[0][3], candidates[0][0])
    return None


def normalize_area(raw_text: str) -> str:
    """从任意文本中识别 Belgrade 标准英文行政区名。"""
    if not raw_text:
        return "Belgrade"

    clean = _norm(raw_text)

    sub_multi_keys = {k for k in SUB_LOCALITY_MAP if " " in k}
    sub_match = _match_area_from_map(clean, SUB_LOCALITY_MAP, sub_multi_keys, single_word_exact_only=True)

    main_multi_keys = {k for k in AREA_MAP if " " in k}
    main_match = _match_area_from_map(clean, AREA_MAP, main_multi_keys)

    if sub_match and main_match:
        sub_name, sub_pos = sub_match
        main_name, main_pos = main_match
        if sub_name == main_name:
            return sub_name if sub_pos <= main_pos else main_name
        tokens = clean.split()
        sub_token_idx = len(clean[:sub_pos].split())
        main_token_idx = len(clean[:main_pos].split())
        token_gap = sub_token_idx - main_token_idx
        if main_pos < sub_pos and token_gap >= 3:
            return main_name
        return sub_name
    elif sub_match:
        return sub_match[0]
    elif main_match:
        return main_match[0]

    m_blok = re.search(r"\bblok\s*(\d+)", clean)
    if m_blok:
        return "Novi Beograd"

    return "Belgrade"


def normalize_4zida_slug(url_slug: str) -> str:
    """专用于从 4zida.rs URL slug 中提取标准化英文行政区名。"""
    if not url_slug:
        return "Belgrade"
    slug = url_slug.lower()
    for slug_key, area_en in FOURZIDA_SLUG_MAP.items():
        if slug_key in slug:
            return area_en
    return normalize_area(slug)


# ── 自测 ──────────────────────────────────────────────────

def _self_test() -> bool:
    passed = 0
    total = 0

    def check(label, actual, expected):
        nonlocal passed, total
        total += 1
        if actual == expected:
            passed += 1
            print(f"  ✅ {total}: {label}")
        else:
            print(f"  ❌ {total}: {label} — expected {expected!r}, got {actual!r}")

    check("Bulbulder → Zvezdara", normalize_area("Bulbulder Mehmeda Sokolovića"), "Zvezdara")
    check("NFKD: Vračaru → Vračar", normalize_area("Stan u Vračaru"), "Vračar")
    check("Lion → Zvezdara", normalize_area("Lion 60m2"), "Zvezdara")
    check("4zida slug: novi-beograd → Novi Beograd", normalize_4zida_slug("/izdavanje-stanova/novi-beograd/..."), "Novi Beograd")
    check("4zida slug: beograd-na-vodi → Savski venac", normalize_4zida_slug("/izdavanje-stanova/beograd-na-vodi/..."), "Savski venac")

    print(f"\n🎯 area_normalizer 完整自测: {passed}/{total} 通过")
    return passed == total


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        ok = _self_test()
        sys.exit(0 if ok else 1)
    print(__doc__)
