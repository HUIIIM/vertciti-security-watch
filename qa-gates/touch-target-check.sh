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

"$PY" - "$URL" <<'PY_EOF'
import os
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1]
BASE = URL.split("#")[0]

# 路由名取自生产 index.html 源码 JS (2026-09-27 核验); 无 demo 路由, 故不测。
ROUTES = ["home", "catalog", "design", "docs", "landscape", "product", "roadmap"]
LANGS = ["zh", "en"]
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
    for route in ROUTES:
        for lang in LANGS:
            key = "#page=%s&lang=%s" % (route, lang)
            resp = page.goto(BASE + key)
            # 同文档 hash 跳转时 goto 返回 None; 有响应时必须 2xx (5xx/404 错误页不能算通过)
            if resp is not None and not resp.ok:
                errors.append("%s: HTTP %d" % (key, resp.status))
            page.wait_for_timeout(2500)  # 等 hash 路由 + JS 按需渲染
            els = page.evaluate(JS_COLLECT)
            if not els:
                errors.append("%s: 0 interactive elements (blank/error page?)" % key)
            n_check = n_ex = 0
            for e in els:
                if e["inlineLink"]:
                    exempt.append((key, e)); n_ex += 1; continue
                n_check += 1
                if e["w"] < MIN or e["h"] < MIN:
                    violations.append((key, e))
            stats[key] = (n_check, n_ex)
    browser.close()

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
