#!/usr/bin/env bash
# =====================================================================
# touch-target-check.sh -- vertciti 触控目标门禁 (T11.1, P0)
# 390px 视口 headless 渲染, 量取所有可见可交互元素 boundingBox,
# 断言 宽>=44 且 高>=44 (WCAG 2.5.8 / Apple HIG 触控下限)。
#
# 用法:
#   ./touch-target-check.sh            # 测生产源文件（其 file:// URL 经
#                                      # 环境变量 TOUCH_TARGET_PROD_FILE 指定）
#   ./touch-target-check.sh <URL>      # 测任意 URL (如 https://vertciti.com/)
#
# 输出:
#   逐路由统计 + 豁免清单 + 违规清单; PASS 打印 PASS, exit 0;
#   FAIL 打印 FAIL 并列违规, exit 1。
#
# 豁免: 纯文本内联链接 (display:inline 的 <a>, 如段落内链接) 不计违规,
#      但计入豁免清单输出备查。
#
# 依赖: playwright sync_api (解释器经环境变量 TOUCH_TARGET_PYTHON 指定) + Chromium
#      (默认 /opt/meta-chromium/chrome, 可经环境变量 TOUCH_TARGET_CHROME 覆盖)
# 注意: localhost 会被 LocalNetworkAccessChecks 拦截, 本地渲染请用 file:// URL。
# 标注: [PASS]/[FAIL]/[EXEMPT] 均为 ASCII 括号。
# =====================================================================
set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "用法: ./touch-target-check.sh [--help] [URL]"
  echo "  390px 触控目标门禁：无参数时经环境变量 TOUCH_TARGET_PROD_FILE 测生产源文件，传 URL 测任意地址（如 https://vertciti.com/）。"
  echo "  路由表可经 TOUCH_TARGET_ROUTES 覆盖（空格分隔；以 / 开头为真实路径，否则为 #page= 路由名）；环境变量未设时读脚本同目录的 touch-target-routes.txt（发布管线定版表）。所有路由渲染结果相同即 FAIL（路由表与站点不符）。"
  echo "  依赖: playwright (解释器经环境变量 TOUCH_TARGET_PYTHON 指定) + /opt/meta-chromium/chrome"
  exit 0
fi

PROD_FILE="${TOUCH_TARGET_PROD_FILE:-}"
URL="${1:-$PROD_FILE}"

if [ -z "$URL" ]; then
  echo "[FAIL] no target: pass a URL argument, or set TOUCH_TARGET_PROD_FILE to the production index.html file:// URL" >&2
  exit 2
fi

PY="${TOUCH_TARGET_PYTHON:-}"

if [ -z "$PY" ]; then
  echo "[FAIL] python not configured: set TOUCH_TARGET_PYTHON to a python interpreter with playwright installed" >&2
  exit 2
fi

if [ ! -x "$PY" ]; then
  echo "[FAIL] python not found: $PY" >&2
  exit 2
fi

# Route-table config: TOUCH_TARGET_ROUTES (env) wins; when unset, read the
# pipeline-set table from touch-target-routes.txt next to this script; when
# that file is absent too, the Python below falls back to its built-in
# hash-route defaults. The effective source is logged so a gate run shows
# which table it measured with.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROUTES_FILE="$SCRIPT_DIR/touch-target-routes.txt"
if [ -n "${TOUCH_TARGET_ROUTES:-}" ]; then
  echo "[routes] source=env routes=$TOUCH_TARGET_ROUTES" >&2
elif [ -f "$ROUTES_FILE" ]; then
  TOUCH_TARGET_ROUTES="$(grep -v '^[[:space:]]*#' "$ROUTES_FILE" | tr '\n' ' ' | tr -s ' ' | sed 's/^ //; s/ $//')"
  export TOUCH_TARGET_ROUTES
  echo "[routes] source=file ($ROUTES_FILE) routes=$TOUCH_TARGET_ROUTES" >&2
else
  echo "[routes] source=default (built-in hash routes)" >&2
fi

"$PY" - "$URL" <<'PY_EOF'
import os
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1]
BASE = URL.split("#")[0]

# 路由名取自生产 index.html 源码 JS (2026-09-27 核验); 无 demo 路由, 故不测。
ROUTES = ["home", "catalog", "design", "docs", "landscape", "product", "roadmap"]
LANGS = ["zh", "en"]
# 环境变量 TOUCH_TARGET_ROUTES (空格分隔) 覆盖路由表: 以 "/" 开头的条目按真实路径
# 访问 (相对 URL 的 origin, 如 "/ /business/ /company/"), 其余按 #page=<名>&lang=<语言> 访问。
# (#6 实测: 线上站点用真实路径导航, 不认 #page= hash 路由。)
if os.environ.get("TOUCH_TARGET_ROUTES", "").strip():
    ROUTES = os.environ["TOUCH_TARGET_ROUTES"].split()


def targets():
    """(key, url) for every page to measure."""
    from urllib.parse import urljoin
    for route in ROUTES:
        if route.startswith("/"):
            yield route, urljoin(BASE, route)
        else:
            for lang in LANGS:
                key = "#page=%s&lang=%s" % (route, lang)
                yield key, BASE + key
MIN = 44.0

JS_COLLECT = """() => {
  const out = [];
  const els = document.querySelectorAll('a,button,input,select,textarea,[role="button"],[onclick]');
  const cssPath = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    let s = el.tagName.toLowerCase();
    const cls = (el.className && typeof el.className === 'string')
      ? el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    if (cls) s += '.' + cls;
    return s;
  };
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    // 完全移出页面的元素 (如 left:-9999px 的跳转链接) 无法被点按, 不计入
    if (r.right <= 0 || r.bottom + window.scrollY <= 0
        || r.left >= document.documentElement.scrollWidth) continue;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    if (el.tagName === 'INPUT' && el.type === 'hidden') continue;
    const text = (el.innerText || el.value || el.getAttribute('aria-label')
      || el.getAttribute('title') || '').trim().replace(/\\s+/g, ' ').slice(0, 30);
    out.push({
      tag: el.tagName.toLowerCase(),
      text: text,
      selector: cssPath(el),
      w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10,
      x: Math.round(r.x), y: Math.round(r.y),
      inlineLink: el.tagName === 'A' && st.display === 'inline'
    });
  }
  return out;
}"""

violations = []   # (route_key, element)
exempt = []       # (route_key, element)
stats = {}        # route_key -> (checked, exempted)
errors = []       # 加载失败 / JS 报错 / 空路由: 一律 FAIL, 不允许在没量到东西时报 PASS

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        executable_path=os.environ.get("TOUCH_TARGET_CHROME", "/opt/meta-chromium/chrome"),
        args=["--no-sandbox", "--disable-dev-shm-usage"])  # 2026-09-27: /dev/shm 仅 794M, 10MB 大页必 crash, 加此 flag 稳定
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: errors.append("JS error: %s" % exc))
    layouts = {}      # key -> 可交互元素布局签名, 用于识别"路由没生效、反复测同一页"
    for key, url in targets():
        resp = page.goto(url)
        # 同文档 hash 跳转时 goto 返回 None; 有响应时必须 2xx (5xx/404 错误页不能算通过)
        if resp is not None and not resp.ok:
            errors.append("%s: HTTP %d" % (key, resp.status))
        page.wait_for_timeout(2500)  # 等 hash 路由 + JS 按需渲染
        els = page.evaluate(JS_COLLECT)
        if not els:
            errors.append("%s: 0 interactive elements (blank/error page?)" % key)
        layouts[key] = tuple((e["selector"], e["text"], e["w"], e["h"], e["x"], e["y"])
                             for e in els)
        n_check = n_ex = 0
        for e in els:
            if e["inlineLink"]:
                exempt.append((key, e)); n_ex += 1; continue
            n_check += 1
            if e["w"] < MIN or e["h"] < MIN:
                violations.append((key, e))
        stats[key] = (n_check, n_ex)
    browser.close()

# 覆盖面自检: 多条路由渲染出完全相同的可交互布局 = 路由表没生效, 实际只测了一页,
# 却报告测了 N 条路由。改用 TOUCH_TARGET_ROUTES 指定站点真实路由。
if len(layouts) > 1 and len(set(layouts.values())) == 1:
    errors.append("all %d routes rendered an identical interactive layout: the route table "
                  "does not match this site, so only one page was really measured "
                  "(set TOUCH_TARGET_ROUTES, e.g. \"/ /business/ /company/\")" % len(layouts))

print("=" * 70)
print("touch-target gate | URL=%s | viewport=390px | min=%dpx" % (URL, MIN))
print("=" * 70)
total_c = sum(v[0] for v in stats.values())
total_e = sum(v[1] for v in stats.values())
for key, (c, x) in stats.items():
    print("%-32s checked=%-4d exempt(inline links)=%d" % (key, c, x))
print("-" * 70)
print("total checked=%d  exempt=%d  violations=%d" % (total_c, total_e, len(violations)))

if exempt:
    print("\n[EXEMPT] inline text links (not counted as violations):")
    for key, e in exempt[:20]:
        print("  %s | <%s> %s | %.1fx%.1f" % (key, e["tag"], e["selector"], e["w"], e["h"]))
    if len(exempt) > 20:
        print("  ... and %d more" % (len(exempt) - 20))

if errors:
    print("\n[FAIL] page did not render as expected (nothing measured = no pass):")
    for msg in errors[:20]:
        print("  " + msg)

if violations:
    print("\n[FAIL] touch target < 44x44:")
    for key, e in violations:
        txt = e["text"] if e["text"] else "(no text)"
        print("  route=%s" % key)
        print("    text=<%s> sel=%s size=%.1fx%.1f pos=(%d,%d)" % (
            txt, e["selector"], e["w"], e["h"], e["x"], e["y"]))
if violations or errors:
    print("\nRESULT: [FAIL] %d violation(s), %d render error(s)" % (len(violations), len(errors)))
    sys.exit(1)

print("\nRESULT: [PASS] all %d interactive elements >= 44x44" % total_c)
PY_EOF
