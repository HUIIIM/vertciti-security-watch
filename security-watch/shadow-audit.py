#!/usr/bin/env python3
"""T2.1 box-shadow 逐项审计脚本（只读）.
扫描目标 index.html 内所有 box-shadow 声明（文件路径经第一个位置参数
或环境变量 SHADOW_AUDIT_SRC 传入，无内置默认目标）,
输出: 选择器 / 行号 / 完整值 / 是否 none / 是否 @media 内.
用法: python3 shadow-audit.py [INDEX.html] [--json PATH] [--table]
      SHADOW_AUDIT_SRC=/path/to/index.html python3 shadow-audit.py
"""
import json
import os
import re
import sys


def style_regions(src):
    regions = []
    for m in re.finditer(r"<style[^>]*>", src, re.I):
        j = src.lower().find("</style>", m.end())
        if j != -1:
            regions.append((m.end(), j))
    return regions


def parse_rules(css):
    """返回每条规则: selector, 声明区起止 offset(相对 css), media(所属 @media 或 None)."""
    rules = []
    stack = []
    i, n = 0, len(css)
    while i < n:
        if css.startswith("/*", i):
            j = css.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        ch = css[i]
        if ch == "{":
            k = i - 1
            while k >= 0 and css[k] not in "{};":
                k -= 1
            sel = css[k + 1:i].strip()
            stack.append(("media" if sel.lower().startswith("@media") else "rule", sel, i))
            i += 1
        elif ch == "}":
            if stack:
                typ, sel, start = stack.pop()
                if typ == "rule":
                    media = None
                    for t, s, _ in stack:
                        if t == "media":
                            media = s
                            break
                    rules.append({"selector": sel, "dstart": start, "dend": i, "media": media})
            i += 1
        else:
            i += 1
    return rules


def main():
    args = sys.argv[1:]
    json_path = None
    want_table = False
    src_arg = None
    i = 0
    while i < len(args):
        if args[i] == "--json" and i + 1 < len(args):
            json_path = args[i + 1]
            i += 2
        elif args[i] == "--table":
            want_table = True
            i += 1
        elif not args[i].startswith("--") and src_arg is None:
            src_arg = args[i]
            i += 1
        else:
            i += 1

    src_path = src_arg or os.environ.get("SHADOW_AUDIT_SRC", "")
    if not src_path:
        print("usage: shadow-audit.py [INDEX.html] [--json PATH] [--table]\n"
              "  target index.html: first positional argument, "
              "or the SHADOW_AUDIT_SRC environment variable",
              file=sys.stderr)
        return 2
    src = open(src_path, encoding="utf-8").read()
    regions = style_regions(src)
    items = []
    for rstart, rend in regions:
        css = src[rstart:rend]
        rules = parse_rules(css)
        for m in re.finditer(r"box-shadow\s*:", css):
            vstart = m.end()
            vend = vstart
            while vend < len(css) and css[vend] not in ";}":
                vend += 1
            value = css[vstart:vend].strip()
            abs_pos = rstart + m.start()
            # 找到最内层包含该声明的规则
            sel, media = None, None
            best = None
            for r in rules:
                a, b = rstart + r["dstart"], rstart + r["dend"]
                if a <= abs_pos < b:
                    span = b - a
                    if best is None or span < best:
                        best = span
                        sel, media = r["selector"], r["media"]
            lineno = src.count("\n", 0, abs_pos) + 1
            items.append({
                "n": len(items) + 1,
                "selector": sel,
                "line": lineno,
                "value": value,
                "is_none": value == "none",
                "in_media": media is not None,
                "media": media,
            })
    # 校验: 声明外还有裸引用(transition 属性名)应为 3
    bare = len(re.findall(r"box-shadow(?!\s*:)", src))
    summary = {
        "string_total": len(re.findall(r"box-shadow", src)),
        "declarations": len(items),
        "bare_refs": bare,
        "none_count": sum(1 for x in items if x["is_none"]),
        "media_count": sum(1 for x in items if x["in_media"]),
        "unresolved_selector": sum(1 for x in items if not x["selector"]),
    }
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "items": items}, f, ensure_ascii=False, indent=1)
    if want_table:
        print("| # | 选择器 | 行 | 值摘要 | none | @media |")
        print("|---|--------|---|--------|------|--------|")
        for x in items:
            v = x["value"]
            vs = (v[:60] + "…") if len(v) > 60 else v
            sel = (x["selector"] or "?")[:70]
            print("| %d | `%s` | %d | `%s` | %s | %s |" % (
                x["n"], sel, x["line"], vs,
                "Y" if x["is_none"] else "", "Y" if x["in_media"] else ""))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if summary["declarations"] != 71:
        print("WARN: declaration count != 71", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
