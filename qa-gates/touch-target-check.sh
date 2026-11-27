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
# 出站校验 (SOTA SEC-A2): 浏览器发出的每个请求 (导航、子资源、WebSocket) 先经同目录
#      egress_guard.py 校验: 只放行 http(s)/ws(s) (目标为 file:// 时另放行 file:)、data:、blob:,
#      主机的全部解析地址必须是公网单播地址 (拒绝环回/私网/链路本地含元数据地址/CGNAT/保留段),
#      解析失败也拒; 被拒请求记为 render error, 结果 FAIL。http(s) 请求一律由拦截器不跟随重定向
#      地取回 (route.fetch max_redirects=0), 浏览器永远拿不到 3xx: 导航被重定向即 FAIL (同门禁 2,
#      只测规范地址, 路由表须列最终地址); 子资源的重定向由拦截器逐跳先校验再取回。
#      浏览器自行发出的连接再核对实际连接地址 (server_addr)。残余: 拦截器取回时由
#      Playwright 自行解析 DNS, 校验与连接之间的 DNS 重绑定无法核对实际地址。
#      浏览器以 --no-proxy-server 直连 (经代理无法核对实际地址);
#      Service Worker 被禁用 (其请求绕过拦截)。QA_EGRESS_ALLOW_HOSTS (空格分隔的精确主机名/IP)
#      豁免指定主机, 供本仓测试在 127.0.0.1 起夹具用, 每次豁免打印 [egress] 行。
# 标注: [PASS]/[FAIL]/[EXEMPT] 均为 ASCII 括号。
# =====================================================================
set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "用法: ./touch-target-check.sh [--help] [URL]"
  echo "  390px 触控目标门禁：无参数时经环境变量 TOUCH_TARGET_PROD_FILE 测生产源文件，传 URL 测任意地址（如 https://vertciti.com/）。"
  echo "  路由表可经 TOUCH_TARGET_ROUTES 覆盖（空格分隔；以 / 开头为真实路径，否则为 #page= 路由名）；环境变量未设时读脚本同目录的 touch-target-routes.txt（发布管线定版表）。所有路由渲染结果相同即 FAIL（路由表与站点不符）。"
  echo "  依赖: playwright (解释器经环境变量 TOUCH_TARGET_PYTHON 指定) + /opt/meta-chromium/chrome"
  echo "  Chromium 沙箱默认开启；以 root 运行或设 TOUCH_TARGET_NO_SANDBOX=1 时关闭（运行日志 [sandbox] 行注明）。"
  echo "  出站校验（SEC-A2）：每个请求的主机都必须只解析到公网地址，否则 FAIL；QA_EGRESS_ALLOW_HOSTS 仅供测试豁免。"
  exit 0
fi

PROD_FILE="${TOUCH_TARGET_PROD_FILE:-}"
URL="${1:-$PROD_FILE}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATE_STARTED_AT="$(date +%s%3N)"; export GATE_STARTED_AT

# 运行记录（OPS-2）：设 GATE_JSON_OUT=<路径> 时，每次运行（含中途退出）结束都写 JSON 记录，
# 与门禁 1/2 同核心字段（run_id、trace_id、result、exit_code 等，见 run_record.py）；本门禁另记
# 逐路由量取数、违规的选择器与尺寸、render error 文本（URL 与原因，不含页面文字）。
# 要求了记录却写不出即 exit 1（fail-closed）。
GATE_DETAIL="$(mktemp)"; export GATE_DETAIL
on_exit() {
  local rc=$? rec_py="${TOUCH_TARGET_PYTHON:-}"
  [ -x "$rec_py" ] || rec_py=python3
  if [ -n "${GATE_JSON_OUT:-}" ]; then
    if [ ! -s "$GATE_DETAIL" ]; then
      printf '{"target": %s, "reason": "gate exited before measuring (exit %d)"}' \
        "$("$rec_py" -I -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$URL")" "$rc" > "$GATE_DETAIL"
    fi
    if ! "$rec_py" -I "$SCRIPT_DIR/run_record.py" write "$GATE_JSON_OUT" touch-target "$rc" "${BASH_SOURCE[0]}" "$GATE_DETAIL"; then
      echo "[FAIL] run record not written to $GATE_JSON_OUT - fail-closed" >&2
      rc=1
    fi
  fi
  rm -f "$GATE_DETAIL"
  exit "$rc"
}
trap on_exit EXIT

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
ROUTES_FILE="$SCRIPT_DIR/touch-target-routes.txt"
# The file holds the live site's real paths, so it only applies to http(s)
# targets: for a file:// target (the production index.html, which routes by
# #page= hash) "/business/" would resolve against file:/// - the filesystem
# root - so file:// keeps the built-in hash routes.
if [ -n "${TOUCH_TARGET_ROUTES:-}" ]; then
  echo "[routes] source=env routes=$TOUCH_TARGET_ROUTES" >&2
elif [ -f "$ROUTES_FILE" ] && [[ "$URL" != http://* && "$URL" != https://* ]]; then
  echo "[routes] source=default (built-in hash routes; $ROUTES_FILE lists site paths and applies to http(s) targets only)" >&2
elif [ -f "$ROUTES_FILE" ]; then
  TOUCH_TARGET_ROUTES="$(grep -v '^[[:space:]]*#' "$ROUTES_FILE" | tr '\n' ' ' | tr -s ' ' | sed 's/^ //; s/ $//')"
  export TOUCH_TARGET_ROUTES
  echo "[routes] source=file ($ROUTES_FILE) routes=$TOUCH_TARGET_ROUTES" >&2
else
  echo "[routes] source=default (built-in hash routes)" >&2
fi

"$PY" - "$URL" "$SCRIPT_DIR" <<'PY_EOF'
import os
import sys
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

URL = sys.argv[1]
sys.path.insert(0, sys.argv[2])
import egress_guard  # noqa: E402  (same directory as this script)
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
        if route.startswith("/") and not BASE.startswith(("http://", "https://")):
            # a site path has no meaning for a file:// target: it would resolve
            # against file:/// (the filesystem root) and "measure" that instead
            errors.append("%s: path routes need an http(s) URL, got %s" % (route, BASE))
            continue
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
errors = []       # 加载失败 / JS 报错 / 空路由 / 出站被拒: 一律 FAIL, 不允许在没量到东西时报 PASS

MAX_REDIRECTS = 5
_egress_cache = {}  # (scheme, host, port) -> reason or None
_exempt_logged = set()


def egress_reason(url):
    """None if the request may go out, else why not (SEC-A2)."""
    from urllib.parse import urlsplit
    scheme = url.split(":", 1)[0].lower()
    if scheme in ("data", "blob", "about"):
        return None
    if scheme == "file":
        return None if BASE.startswith("file:") else "file: request from a non-file target"
    if scheme in ("ws", "wss"):
        url = ("http" if scheme == "ws" else "https") + url[len(scheme):]
        scheme = "http" if scheme == "ws" else "https"
    if scheme not in ("http", "https"):
        return "scheme %r not allowed" % scheme
    parts = urlsplit(url)
    key = (scheme, parts.hostname, parts.port)
    if key not in _egress_cache:
        host, _port, _ips, err = egress_guard.check_url(url)
        _egress_cache[key] = err
        if err is None and egress_guard.host_exempt(host) and host not in _exempt_logged:
            _exempt_logged.add(host)
            print("[egress] %s exempted from the non-public check via QA_EGRESS_ALLOW_HOSTS "
                  "(tests only)" % host, file=sys.stderr)
    return _egress_cache[key]


def guard_request(route):
    url = route.request.url
    reason = egress_reason(url)
    if reason is not None:
        errors.append("egress blocked (SEC-A2): %s: %s" % (url[:120], reason))
        route.abort("blockedbyclient")
        return
    if url.split(":", 1)[0].lower() not in ("http", "https"):
        route.continue_()
        return
    # Playwright calls a route handler only for the first URL of a redirect chain,
    # and the browser follows any 3xx it is handed - even one we fulfil - without
    # routing the next hop (measured: a 302 to localhost reached the server). So
    # the browser must never see a redirect: every http(s) request is fetched here
    # with max_redirects=0. A navigation that redirects FAILs (like gate 2, gate 3
    # measures canonical URLs: list the final URL in the route table); a
    # subresource redirect is followed here, each hop checked before it connects,
    # and only the final response is handed to the browser.
    from urllib.parse import urljoin
    navigation = route.request.is_navigation_request()
    hop = url
    for _ in range(MAX_REDIRECTS + 1):
        try:
            resp = route.fetch(url=hop, max_redirects=0)
        except PlaywrightError:
            route.abort("failed")
            return
        location = resp.headers.get("location")
        if not (300 <= resp.status < 400 and location):
            route.fulfill(response=resp)
            return
        nxt = urljoin(hop, location)
        if navigation:
            errors.append("%s: navigation redirected (HTTP %d -> %s); gate 3 measures canonical "
                          "URLs only - list the final URL in the route table"
                          % (url[:120], resp.status, nxt[:120]))
            route.abort("blockedbyclient")
            return
        reason = egress_reason(nxt)
        if reason is not None:
            errors.append("egress blocked (SEC-A2): redirect %s -> %s: %s"
                          % (hop[:120], nxt[:120], reason))
            route.abort("blockedbyclient")
            return
        hop = nxt
    errors.append("egress blocked (SEC-A2): %s: more than %d redirects" % (url[:120], MAX_REDIRECTS))
    route.abort("blockedbyclient")


def guard_websocket(ws):
    reason = egress_reason(ws.url)
    if reason is None:
        ws.connect_to_server()
        return
    errors.append("egress blocked (SEC-A2): %s: %s" % (ws.url[:120], reason))
    ws.close()


def check_connected(resp):
    """After the connection: the address really connected to must be allowed too."""
    try:
        addr = resp.server_addr()
    except PlaywrightError:
        addr = None
    if not addr:
        return  # file:, data:, cache: no network connection was made
    from urllib.parse import urlsplit
    host = urlsplit(resp.url).hostname or ""
    if not (egress_guard.host_exempt(host) or egress_guard.ip_allowed(addr["ipAddress"])):
        errors.append("egress blocked (SEC-A2): %s connected to non-public address %s"
                      % (resp.url[:120], addr["ipAddress"]))

with sync_playwright() as pw:
    # Chromium 沙箱默认开启（被测页面的 JS 在此执行；#6 SEC-A3）。只在两种情况下关闭：
    # 以 root 运行（Chromium 拒绝在 root 下启用沙箱："Chromium sandboxing failed!"），
    # 或显式设 TOUCH_TARGET_NO_SANDBOX=1。注意 Playwright 的 chromium_sandbox 默认为
    # False（会自行加 --no-sandbox），所以必须显式传 True 才真正开启沙箱。
    no_sandbox = (os.environ.get("TOUCH_TARGET_NO_SANDBOX") == "1"
                  or (hasattr(os, "geteuid") and os.geteuid() == 0))
    print("[sandbox] chromium sandbox=%s%s" % (
        "off" if no_sandbox else "on",
        " (root or TOUCH_TARGET_NO_SANDBOX=1)" if no_sandbox else ""), file=sys.stderr)
    browser = pw.chromium.launch(
        executable_path=os.environ.get("TOUCH_TARGET_CHROME", "/opt/meta-chromium/chrome"),
        chromium_sandbox=not no_sandbox,
        # --disable-dev-shm-usage: 2026-09-27 /dev/shm 仅 794M, 10MB 大页必 crash, 加此 flag 稳定;
        # --no-proxy-server: 直连, 让 server_addr 核对的是真实目标地址 (SEC-A2)
        args=["--disable-dev-shm-usage", "--no-proxy-server"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              has_touch=True, is_mobile=True,
                              service_workers="block")  # SW 请求绕过 route 拦截
    ctx.route("**/*", guard_request)
    ctx.route_web_socket("**/*", guard_websocket)
    page = ctx.new_page()
    page.on("pageerror", lambda exc: errors.append("JS error: %s" % exc))
    page.on("response", check_connected)
    layouts = {}      # key -> 可交互元素布局签名, 用于识别"路由没生效、反复测同一页"
    for key, url in targets():
        try:
            resp = page.goto(url)
        except PlaywrightError as exc:
            errors.append("%s: navigation failed: %s" % (key, str(exc).splitlines()[0]))
            stats[key] = (0, 0)
            continue
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


def write_detail():
    """Gate-specific fields for the run record (no page text: selectors, sizes, URLs only)."""
    import json
    detail = {
        "target": URL,
        "viewport_px": 390,
        "min_px": MIN,
        "sandbox": "off" if no_sandbox else "on",
        "egress_exempt_hosts": sorted(_exempt_logged),
        "routes": [{"route": k, "checked": c, "exempt": x} for k, (c, x) in stats.items()],
        "checked": total_c,
        "violations": [{"route": k, "tag": e["tag"], "selector": e["selector"],
                        "w": e["w"], "h": e["h"]} for k, e in violations],
        "render_errors": errors[:50],
    }
    with open(os.environ["GATE_DETAIL"], "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False)


if os.environ.get("GATE_DETAIL"):
    write_detail()

if violations or errors:
    print("\nRESULT: [FAIL] %d violation(s), %d render error(s)" % (len(violations), len(errors)))
    sys.exit(1)

print("\nRESULT: [PASS] all %d interactive elements >= 44x44" % total_c)
PY_EOF
