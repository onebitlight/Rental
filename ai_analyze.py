# -*- coding: utf-8 -*-
"""
ai_analyze.py — 通用 AI 中文提炼与塞尔维亚房源属性标准化映射

职责：
  接收从任意房源网详情页抓到的原始文本 + 已提取属性（字典形式），
  调用本机 OpenClaw 配置的 siliconflow LLM，生成：
    1. 核心亮点（3-5 句中文）
    2. 标准化中文属性映射（把不同网站五花八门的原生字段名 → 统一中文 KV）
    3. 居住与交易政策（宠物/押金/最短租期/起租）

设计要点：
  - 不绑定任何单一网站；输入是"原始文本 + 原生属性 dict"，输出是统一 schema。
  - AI Key 从 ~/.openclaw/openclaw.json 的 models.providers.siliconflow.apiKey 读取，
    与 Gateway 同一套凭据，不硬编码、不外泄。
  - 具备健壮降级：AI 调用失败/超时/返回无效时，用规则兜底给出可用输出，绝不中断渲染。
"""
import json, os, re, subprocess
import urllib.request
import pathlib

# ---- AI 配置 ----
OPENCLAW_JSON = pathlib.Path.home() / '.openclaw' / 'openclaw.json'
AI_MODEL = 'deepseek-ai/DeepSeek-V4-Flash'
AI_ENDPOINT = 'https://api.siliconflow.cn/v1/chat/completions'
AI_TIMEOUT = 60
_MAX_INPUT_CHARS = 6000          # 控制送入 AI 的原始文本上限（防超长/省钱）
_MAX_ATTR_PAIRS = 40             # 原生属性最多送前 N 条

# 标准中文键名白名单（渲染端统一展示这些字段，值由 AI 标准化）
STD_KEYS = [
    '供暖', '楼层', '面积', '户型', '家具状态', '车位',
    '电梯', '阳台', '地下室/储藏室', '空调', '网络', '装修状态',
    '户型结构', '朝向', '建筑年份', '能源等级',
]


def _read_api_key():
    """从 OpenClaw 配置文件读取 siliconflow API Key。找不到返回 None。"""
    try:
        d = json.loads(OPENCLAW_JSON.read_text(encoding='utf-8'))
        k = d['models']['providers'].get('siliconflow', {}).get('apiKey')
        if isinstance(k, str) and k and k != '__OPENCLAW_REDACTED__':
            return k
    except Exception:
        pass
    return None


def _call_llm(system, user):
    """调用 siliconflow chat/completions。成功返回内容字符串，失败返回 None。"""
    key = _read_api_key()
    if not key:
        return None
    body = json.dumps({
        'model': AI_MODEL,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'temperature': 0.3,
        'max_tokens': 1500,
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        AI_ENDPOINT, data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as r:
            data = json.loads(r.read().decode('utf-8'))
        return data['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"⚠️ ai_analyze: LLM 调用失败: {e}", file=sys.stderr)
        return None


def _extract_json_block(text):
    """从 LLM 回复里稳健提取 JSON 对象（可能被 ```json 包裹或前后有废话）。"""
    if not text:
        return None
    t = text.strip()
    # 去掉 markdown 代码块围栏
    t = re.sub(r'^```(?:json)?\s*', '', t)
    t = re.sub(r'\s*```$', '', t)
    # 直接尝试解析
    try:
        return json.loads(t)
    except Exception:
        pass
    # 尝试截取第一个 { ... 最后一个 }
    m = re.search(r'\{.*\}', t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# ---------- 规则兜底 ----------

_HEAT_WORDS = [
    ('中央供暖/集中供暖', ['centralno grejanje', 'central heating', 'centralno', 'city heating', 'daljinsko', '集中供暖']),
    ('燃气供暖', ['gasno', 'gas ', 'gasn', 'gas heating', '燃气']),
    ('电暖', ['električno', 'elektricno', 'električ', 'electric', 'elektro', '电暖', '电热']),
    ('地暖', ['podno grejanje', 'podno', '地暖']),
]
_AMENITY_WORDS = {
    '车位': ['parking', 'garaz', 'garaž', 'parking mesto', '车位', '车库'],
    '电梯': ['lift', '电梯'],
    '阳台': ['terasa', 'terace', 'balkon', '阳台'],
    '地下室/储藏室': ['podrum', 'ostava', 'špajz', 'shupe', '地下室', '储藏'],
    '空调': ['klima', 'klimatiz', '空调'],
    '网络/网络接口': ['internet', 'wifi', '网络'],
}
_FURNITURE_WORDS = ['namesten', 'namešten', 'namest', 'opremljen', 'oprem', 'furnished', '家具', '配好', '全配', '拎包']
_PET_POSITIVE = ['ljubimc', 'pet friendly', 'mogući ljubimci', 'dz ljubimac', '宠物', '允许养']
_PET_NEGATIVE = ['bez ljubimac', 'bez kućnih', 'no pets', 'no pet', 'ne dozvoljava se', '禁宠', '不允许养', '不接受宠物']
_DEPOSIT = ['depozit', 'kaucija', 'deposit', '押金', '押一']
_LEASE = ['minimum', 'minimalno', 'najmanje', '最短租期', '起租', '最少']


def _build_fallback(raw_text, attrs):
    """无 AI 时的规则兜底：尽力给出中文亮点、标准化映射、政策。"""
    t = ' '.join([
        str(raw_text or ''),
        ' '.join(f'{k} {v}' for k, v in (attrs or {}).items()),
    ]).lower()

    # 标准化属性映射（原生 attrs → 统一中文 key；原生名可直读则保底）
    std = {}
    for k, v in (attrs or {}).items():
        if isinstance(v, (str, int, float)) and str(v).strip():
            std.setdefault(_s_zh_key(k), str(v).strip())

    # 从原文补识别供暖/家具/车位等
    for label, words in _HEAT_WORDS:
        if any(w in t for w in words):
            std.setdefault('供暖', label)
            break
    if any(w in t for w in _FURNITURE_WORDS):
        std.setdefault('家具状态', '已配家具')
    for k, words in _AMENITY_WORDS.items():
        if any(w in t for w in words):
            std.setdefault(k, '有')

    # 政策
    policy = []
    if any(w in t for w in _PET_POSITIVE) and not any(w in t for w in _PET_NEGATIVE):
        policy.append('允许养宠物')
    elif any(w in t for w in _PET_NEGATIVE):
        policy.append('不允许养宠物')
    if any(w in t for w in _DEPOSIT):
        policy.append('需缴纳押金')
    if any(w in t for w in _LEASE):
        policy.append('可能设有最短租期')

    highlights = ("该房源位于贝尔格莱德，已按预算筛选通过。"
                  "建议直接点击下方按钮前往原平台查看完整多图和地图位置，"
                  "并通过平台的联系功能与该房源的发布方沟通看房与租约细节。")
    return {
        'highlights': highlights,
        'std_attrs': std or {'面积': '', '户型': '见原网页'},
        'policy': policy or ['详情以原网页为准'],
        'ai': False,
    }


def _s_zh_key(raw):
    """原生属性名 → 中文键名近似直译（兜底）。"""
    s = str(raw or '').strip()
    sr_map = {
        'kvadratura': '面积', 'broj soba': '户型', 'spratnost': '楼层',
        'grejanje': '供暖', 'namešten': '家具状态', 'površina': '面积',
        'cena': '价格', 'sprat': '楼层', 'ukupna površina': '面积',
        'korisna površina': '面积', 'ukupan broj spratova': '总楼层',
    }
    low = s.lower()
    # 精确/包含匹配
    for k, v in sr_map.items():
        if low == k or low.startswith(k):
            return v
    # 英文常见
    en_map = {
        'price': '价格', 'area': '面积', 'size': '面积', 'rooms': '户型',
        'floor': '楼层', 'heating': '供暖', 'furnished': '家具状态',
        'parking': '车位', 'toilet': '卫浴', 'condition': '装修状态',
    }
    for k, v in en_map.items():
        if low == k or low.startswith(k):
            return v
    return s


# ---------- 主入口 ----------

def analyze(raw_text, attrs=None, extra_context=''):
    """
    对一条房源做 AI 中文提炼 + 属性标准化。

    参数：
      raw_text      — 从详情页抓取的原始正文/网页全文本（塞尔维亚语或英文）
      attrs         — 从详情页提取的原生属性 dict（{原生字段名: 值}）
      extra_context — 可选补充上下文（如所在城市、来源站点），用于辅助 AI 判断

    返回 dict：
      {
        'highlights': '<3-5句中文>',
        'std_attrs':  {中文键: 值, ...},
        'policy':     ['允许养宠物', '需缴纳押金', ...],
        'ai': True/False,        # 是否由真实 AI 生成（False=规则兜底）
      }
    """
    native = dict(attrs or {})
    text_for_ai = re.sub(r'\s+', ' ', str(raw_text or ''))[:_MAX_INPUT_CHARS]
    attr_items = list(native.items())[:_MAX_ATTR_PAIRS]

    system = (
        "你是塞尔维亚贝尔格莱德房产领域的专业中文助手。你需把任意塞尔维亚房源网页的"
        "原始信息提炼为简明中文，输出结构严格为 JSON，不要任何额外文字。\n"
        f"可输出的标准中文键集合：{STD_KEYS}\n"
        "输出 JSON 结构：\n"
        "{\n"
        "  \"highlights\": \"3-5 句中文亮点总结：涵盖房屋朝向/采光/装修布局优势、"
        "交通与周边配套（超市/公交/学校）、以及特殊限制（如仅限长租、押一付一等）。简洁通顺。\",\n"
        "  \"std_attrs\": {\"供暖\": \"集中供暖\", \"面积\": \"50 m²\", ...}，把原生字段统一映射为"
        "标准中文键；值用中文并尽量带上单位；无法判定的键省略。\n"
        "  \"policy\": [\"允许养宠物\", \"需押金\", \"最短租期 X 个月\"]，据原文判断居住与交易政策，"
        "不确定的不要写。\n"
        "}\n"
        "注意：highlights 必须是真的基于原文内容，不要编造原文没有的信息；若原文信息极少，"
        "则以审慎语气给出可确认的要点并建议查看原网页。"
    )
    user = (
        "请分析以下塞尔维亚房源网页抓取到的信息。\n"
        f"补充背景：{extra_context}\n\n"
        "【原生属性键值】(字段名: 值)：\n" +
        ("\n".join(f"  {k}: {v}" for k, v in attr_items) if attr_items else "  （无）") +
        "\n\n【原始网页文本】：\n" +
        (text_for_ai if text_for_ai.strip() else "（无长文本，仅属性）") +
        "\n\n请按要求输出 JSON。"
    )

    # 尝试真实 AI
    reply = _call_llm(system, user)
    data = _extract_json_block(reply)
    if data and isinstance(data, dict):
        highlights = str(data.get('highlights') or '').strip()
        std = data.get('std_attrs')
        std = {k: str(v) for k, v in std.items()} if isinstance(std, dict) else {}
        pol = data.get('policy')
        pol = [str(x) for x in pol] if isinstance(pol, list) else []
        # 至少要有 highlights 才算有效
        if highlights:
            print("✅ ai_analyze: LLM 提炼成功")
            return {
                'highlights': highlights,
                'std_attrs': std,
                'policy': pol,
                'ai': True,
            }

    # 降级：规则兜底
    print("⚠️ ai_analyze: 使用规则兜底（AI 不可用或无效）")
    return _build_fallback(text_for_ai, native)


if __name__ == '__main__':
    # 自测
    test_text = ("Izdaje se dvosoban stan od 50m2, III sprat od 5, centralno grejanje, "
                 "kompletno namešten, terasa, lift, parking mesto, dozvoljeni ljubimci, depozit 2 meseca.")
    test_attrs = {'Kvadratura': '50 m2', 'Broj soba': '2', 'Spratnost': 'III/5', 'Grejanje': 'CG'}
    print(json.dumps(analyze(test_text, test_attrs), ensure_ascii=False, indent=2))
