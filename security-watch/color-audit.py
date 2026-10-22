#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vertciti 色彩审计脚本（T1.1，P0，只读）
扫描 deploy-prod-root/index.html 的 <style> 内联 CSS（含 @media）以及 style= 属性，
提取全部色值（hex / rgb() / rgba() / hsl() / hsla()），统计出现次数与示例位置。

只读：绝不修改输入文件。
用法: python3 color-audit.py [path/to/index.html] [--json out.json]

归一化规则：
- hex：小写；#rgb/#rgba 展开；不同写法但同色归一为同一 canonical key
- rgb()/rgba()/hsl()/hsla()：数值归一，alpha=1 时归一为 #rrggbb，否则为 rgba(r,g,b,a)
- canonical key 格式：不透明 -> "#rrggbb"；半透明 -> "rgba(r, g, b, a)"

data URI 里的 #xxx 一律剔除（只在 CSS 声明值位置提取）；紧跟 url( 的 #id 引用剔除。
"""
import bisect
import colorsys
import json
import re
import sys
from collections import Counter

HEX_RE  = re.compile(r'#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{4}\b|#[0-9a-fA-F]{3}\b')
FUNC_RE = re.compile(r'\b(rgba?|hsla?)\(\s*([^)]*)\)', re.I)
STYLE_BLOCK_RE = re.compile(r'<style[^>]*>(.*?)</style>', re.I | re.S)
STYLE_ATTR_RE  = re.compile(r'''\bstyle\s*=\s*(["'])(.*?)\1''', re.I | re.S)
COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)
DATAURI_RE = re.compile(r'url\(\s*["\']?data:[^)]*\)', re.I)
RULE_RE    = re.compile(r'([^{}]+)\{([^{}]*)\}')
MEDIA_RE   = re.compile(r'@media[^{]*\{', re.I)

def blank_keep_newlines(m):
    """把匹配块替换为等长占位：换行位置保留换行，其余为空格。
    保证替换后全文长度与换行位置完全不变，后续行号与原文件一致。"""
    return ''.join('\n' if c == '\n' else ' ' for c in m.group(0))

def strip_comments_keep_lines(css):
    """删注释但保留长度与换行位置，保证后续行号与原文件一致。"""
    return COMMENT_RE.sub(blank_keep_newlines, css)

def mask_data_uris(css):
    """用等长空格遮掉 data URI（换行保留），保证偏移不变。"""
    return DATAURI_RE.sub(blank_keep_newlines, css)

def line_offsets(text):
    offs = [0]
    for m in re.finditer(r'\n', text):
        offs.append(m.end())
    return offs

def lineno(offs, pos):
    return bisect.bisect_right(offs, pos)

def expand_hex(h):
    h = h.lower()
    body = h[1:]
    if len(body) == 3:
        return '#' + ''.join(c * 2 for c in body)
    if len(body) == 4:  # #rgba -> expand rgb, keep alpha
        rgb = ''.join(c * 2 for c in body[:3])
        a = int(body[3] * 2, 16)
        return ('#' + rgb, a / 255.0)
    if len(body) == 8:
        return ('#' + body[:6], int(body[6:], 16) / 255.0)
    return '#' + body

def canonical_hex(h):
    """hex -> (canonical_key, r, g, b, a)"""
    x = expand_hex(h)
    if isinstance(x, tuple):
        hx, a = x
    else:
        hx, a = x, 1.0
    r, g, b = int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16)
    if a >= 1.0:
        return hx, r, g, b, 1.0
    return 'rgba(%d, %d, %d, %s)' % (r, g, b, round(a, 3)), r, g, b, round(a, 3)

def parse_num(tok, scale255=True):
    tok = tok.strip()
    if tok.endswith('%'):
        v = float(tok[:-1])
        return (v / 100.0 * 255.0) if scale255 else v / 100.0
    return float(tok)

def parse_func(name, inner):
    name = name.lower()
    parts = inner.strip().split('/')
    alpha = 1.0
    if len(parts) == 2:
        a = parts[1].strip()
        alpha = float(a[:-1]) / 100.0 if a.endswith('%') else float(a)
    comps = parts[0].replace(',', ' ').split()
    if name.startswith('rgb'):
        # rgba(R,G,B,A) 四逗号写法：最后一个分量是 alpha
        if len(comps) == 4 and name == 'rgba':
            a4 = comps.pop()
            alpha = float(a4[:-1]) / 100.0 if a4.endswith('%') else float(a4)
        if len(comps) != 3:
            return None
        r = parse_num(comps[0])
        g = parse_num(comps[1])
        b = parse_num(comps[2])
    else:
        if len(comps) == 4 and name == 'hsla':
            a4 = comps.pop()
            alpha = float(a4[:-1]) / 100.0 if a4.endswith('%') else float(a4)
        if len(comps) != 3:
            return None
        h = comps[0]
        for suf in ('deg', 'grad', 'rad', 'turn'):
            if h.endswith(suf):
                h = h[:-len(suf)]
        h = float(h) % 360.0
        s = parse_num(comps[1], scale255=False)
        lum = parse_num(comps[2], scale255=False)
        rf, gf, bf = colorsys.hls_to_rgb(h / 360.0, max(0.0, min(1.0, lum)),
                                         max(0.0, min(1.0, s)))
        r, g, b = rf * 255.0, gf * 255.0, bf * 255.0
    r, g, b = int(round(r)), int(round(g)), int(round(b))
    if alpha >= 1.0:
        return '#%02x%02x%02x' % (r, g, b), r, g, b, 1.0
    a3 = round(alpha, 3)
    return 'rgba(%d, %d, %d, %s)' % (r, g, b, a3), r, g, b, a3

def media_spans(css):
    """返回 [(start, end, query_text)]，用于标注规则所处的 @media。"""
    spans = []
    for m in MEDIA_RE.finditer(css):
        depth = 0
        i = m.end() - 1
        n = len(css)
        while i < n:
            if css[i] == '{':
                depth += 1
            elif css[i] == '}':
                depth -= 1
                if depth == 0:
                    spans.append((m.start(), i + 1, css[m.start():m.end() - 1].strip()))
                    break
            i += 1
    return spans

def in_media(spans, pos):
    for s, e, q in spans:
        if s <= pos < e:
            return q
    return None

def extract_from_decls(decls_text, selector_ctx, line_of, records):
    """逐条声明扫描色值。line_of 接收"相对 decls_text 起始"的偏移。"""
    pos = 0
    for decl in decls_text.split(';'):
        dpos = decls_text.find(decl, pos)
        if ':' not in decl:
            if dpos >= 0:
                pos = dpos + len(decl)
            continue
        prop, _, val = decl.partition(':')
        prop = prop.strip()
        try:
            vpos = decl.index(val)
        except ValueError:
            vpos = 0
        base = (dpos if dpos >= 0 else 0) + vpos
        for m in HEX_RE.finditer(val):
            # 剔除 url(#...) 之类的 id 引用
            before = val[max(0, m.start() - 4):m.start()]
            if before.endswith('url('):
                continue
            key, r, g, b, a = canonical_hex(m.group(0))
            records.append(dict(key=key, raw=m.group(0), prop=prop,
                                selector=selector_ctx,
                                line=line_of(base + m.start()),
                                r=r, g=g, b=b, a=a))
        for m in FUNC_RE.finditer(val):
            try:
                parsed = parse_func(m.group(1), m.group(2))
            except Exception:
                continue
            if not parsed:
                continue
            key, r, g, b, a = parsed
            records.append(dict(key=key, raw=m.group(0), prop=prop,
                                selector=selector_ctx,
                                line=line_of(base + m.start()),
                                r=r, g=g, b=b, a=a))
        if dpos >= 0:
            pos = dpos + len(decl)

def audit(path):
    text = open(path, encoding='utf-8').read()
    offs = line_offsets(text)
    records = []

    blocks = list(STYLE_BLOCK_RE.finditer(text))
    for b in blocks:
        css = strip_comments_keep_lines(b.group(1))
        css = mask_data_uris(css)
        spans = media_spans(css)
        for rm in RULE_RE.finditer(css):
            raw_sel = rm.group(1).strip()
            if not raw_sel or raw_sel.startswith('@'):
                continue
            sel = ' '.join(raw_sel.split())
            media = in_media(spans, rm.start())
            ctx = ('@media %s >> %s' % (media.replace('@media', '').strip(), sel)
                   if media else sel)
            body = rm.group(2)
            base = b.start(1)
            def line_of(p, _base=base, _rm=rm):
                return lineno(offs, _base + _rm.start(2) + p)
            extract_from_decls(body, ctx, line_of, records)

    # style= 属性
    for sm in STYLE_ATTR_RE.finditer(text):
        val = sm.group(2)
        if not val.strip():
            continue
        tag_ctx = text[max(0, sm.start() - 80):sm.start()].split('<')[-1][:60]
        ctx = 'style-attr <%s>' % tag_ctx.strip()
        attr_start = sm.start(2)
        def line_of(p, _s=attr_start):
            return lineno(offs, _s + p)
        extract_from_decls(val, ctx, line_of, records)

    return records, len(blocks)

def cluster(records):
    """按色相/明度/用途做近义簇。返回 [(cluster_name, [keys])]。"""
    by_key = {}
    for rec in records:
        by_key.setdefault(rec['key'], rec)
    clusters = []
    def hue_group(r, g, b):
        h, lum, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        return h * 360.0, lum, s
    groups = {
        'alpha 半透明': [], 'near-white 白/极浅': [], 'light-gray 浅灰': [],
        'gray 中灰': [], 'dark-gray 深灰': [], 'near-black 近黑': [],
        'red 红/粉': [], 'orange 橙/琥珀': [], 'yellow 黄': [],
        'green 绿/薄荷': [], 'teal 青': [], 'blue 蓝': [],
        'purple 紫': [], 'magenta 品红': [],
    }
    for key, rec in by_key.items():
        r, g, b, a = rec['r'], rec['g'], rec['b'], rec['a']
        if a < 1.0:
            groups['alpha 半透明'].append(key)
            continue
        h, _lum, s = hue_group(r, g, b)
        mx = max(r, g, b) / 255.0
        mn = min(r, g, b) / 255.0
        if s < 0.10 or (mx - mn) < 0.06:
            if mx > 0.96:
                groups['near-white 白/极浅'].append(key)
            elif mx > 0.80:
                groups['light-gray 浅灰'].append(key)
            elif mx > 0.55:
                groups['gray 中灰'].append(key)
            elif mx > 0.25:
                groups['dark-gray 深灰'].append(key)
            else:
                groups['near-black 近黑'].append(key)
            continue
        if h < 15 or h >= 345:
            groups['red 红/粉'].append(key)
        elif h < 45:
            groups['orange 橙/琥珀'].append(key)
        elif h < 70:
            groups['yellow 黄'].append(key)
        elif h < 160:
            groups['green 绿/薄荷'].append(key)
        elif h < 200:
            groups['teal 青'].append(key)
        elif h < 260:
            groups['blue 蓝'].append(key)
        elif h < 290:
            groups['purple 紫'].append(key)
        else:
            groups['magenta 品红'].append(key)
    for name, keys in groups.items():
        if keys:
            clusters.append((name, sorted(keys,
                key=lambda k: (by_key[k]['r'], by_key[k]['g'], by_key[k]['b']))))
    return clusters, by_key

def main():
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else None
    if not path:
        print('用法: python3 color-audit.py <index.html> [--json out.json]')
        sys.exit(1)
    json_out = None
    if '--json' in sys.argv:
        json_out = sys.argv[sys.argv.index('--json') + 1]
    records, nblocks = audit(path)
    counts = Counter(r['key'] for r in records)
    first = {}
    for r in records:
        if r['key'] not in first:
            first[r['key']] = r
    clusters, by_key = cluster(records)
    print('style 块数: %d' % nblocks)
    print('色值出现总次数: %d' % len(records))
    print('去重色总数(canonical): %d' % len(counts))
    print()
    print('== 频次 Top 20 ==')
    for k, c in counts.most_common(20):
        fr = first[k]
        print('%-22s %4d  例: L%d %s { %s: ... } (raw=%s)' % (
            k, c, fr['line'], fr['selector'][:60], fr['prop'], fr['raw']))
    print()
    print('== 近义簇 ==')
    for name, keys in clusters:
        print('[%s] %d 色: %s' % (name, len(keys), ', '.join(keys)))
    print()
    locked = ['#16a34a', '#d97706', '#6b7280']
    print('== v1 锁定三色核验 ==')
    for k in locked:
        print('%s 出现 %d 次' % (k, counts.get(k, 0)))
    if json_out:
        data = dict(
            input=path, style_blocks=nblocks,
            total_occurrences=len(records), unique_colors=len(counts),
            counts=counts.most_common(),
            examples={k: dict(line=first[k]['line'], selector=first[k]['selector'],
                              prop=first[k]['prop'], raw=first[k]['raw'])
                      for k in counts},
            clusters=[dict(name=n, keys=ks) for n, ks in clusters],
            locked={k: counts.get(k, 0) for k in locked},
        )
        json.dump(data, open(json_out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print('JSON 已写: %s' % json_out)

if __name__ == '__main__':
    main()
