#!/usr/bin/env bash
# =====================================================================
# homepage-200-check.sh -- vertciti 门禁 2：首页必须返回 HTTP 200
# 此前门禁 2 只是文档里的一行 `curl -sI URL | head -1`：退出码恒为 0（head 总成功），
# 在代理环境下第一行还是代理的 "200 Connection Established"，与站点状态无关。
# 本脚本取站点自身的最终状态码（curl -w '%{http_code}'，不跟随重定向），非 200 即 FAIL。
#
# 用法:
#   ./homepage-200-check.sh            # 测 https://vertciti.com/
#   ./homepage-200-check.sh <URL>      # 测任意 URL
# 退出码: 0=PASS(200)  1=FAIL(非 200 / 连接失败 / 超时 / 出站地址被拒)
#
# 出站校验（SOTA SEC-A2）：连接前用同目录 egress_guard.py 解析主机，所有解析地址都必须是
# 公网单播地址（拒绝环回、私网、链路本地含 169.254.169.254 元数据地址、CGNAT、保留段，
# 以及它们的 IPv4 映射形式）；解析失败即 FAIL。curl 以 --resolve 钉住已校验的地址、
# --noproxy '*' 直连（经代理时无法核对实际连接地址），连接后再核对 %{remote_ip}
# 与钉住地址一致且为公网地址。只发一跳：不跟随重定向。
# QA_EGRESS_ALLOW_HOSTS（空格分隔的精确主机名/IP）豁免指定主机的非公网检查，供本仓
# 测试在 127.0.0.1 上起夹具用；每次豁免都会打印 [egress] 行。
# 依赖: python3（可经 HOMEPAGE_CHECK_PYTHON 指定解释器）、curl。
# 标注: [PASS]/[FAIL] 均为 ASCII 括号。
# =====================================================================
set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "用法: ./homepage-200-check.sh [--help] [URL]"
  echo "  门禁 2：URL（默认 https://vertciti.com/）必须直接返回 HTTP 200；重定向、4xx/5xx、连接失败均 FAIL。"
  exit 0
fi

URL="${1:-https://vertciti.com/}"
TIMEOUT="${HOMEPAGE_CHECK_TIMEOUT:-20}"
PY="${HOMEPAGE_CHECK_PYTHON:-python3}"
QA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$QA_DIR/egress_guard.py"
GATE_STARTED_AT="$(date +%s%3N)"; export GATE_STARTED_AT

# 运行记录（OPS-2）：设 GATE_JSON_OUT=<路径> 时，每次运行（含中途退出）结束都写 JSON 记录，
# 与门禁 1 同核心字段（run_id、trace_id、result、exit_code 等，见 run_record.py）；
# 本门禁另记 target、http_code、remote_ip、pinned_ip、egress_exempt、reason，不含响应内容。
# 要求了记录却写不出即 exit 1（fail-closed）。
D_HOST=""; D_IP=""; D_REMOTE=""; D_CODE=""; D_EXEMPT=0; D_REASON=""
on_exit() {
  local rc=$? detail
  if [ -n "${GATE_JSON_OUT:-}" ]; then
    detail="$(mktemp)"
    if ! "$PY" -I -c 'import json, sys
k = ["target", "host", "pinned_ip", "remote_ip", "http_code", "egress_exempt", "reason"]
v = sys.argv[2:]
d = dict(zip(k, [x or None for x in v]))
d["egress_exempt"] = v[5] == "1"
json.dump(d, open(sys.argv[1], "w"), ensure_ascii=False)' "$detail" "$URL" "$D_HOST" "$D_IP" "$D_REMOTE" "$D_CODE" "$D_EXEMPT" "$D_REASON" \
       || ! "$PY" -I "$QA_DIR/run_record.py" write "$GATE_JSON_OUT" homepage-200 "$rc" "${BASH_SOURCE[0]}" "$detail"; then
      echo "[FAIL] 运行记录写入失败 $GATE_JSON_OUT —— fail-closed"
      rc=1
    fi
    rm -f "$detail"
  fi
  exit "$rc"
}
trap on_exit EXIT
fail() { D_REASON="$1"; echo "[FAIL] $1"; exit 1; }

if ! command -v "$PY" >/dev/null 2>&1 || [ ! -f "$GUARD" ]; then
  trap - EXIT
  echo "[FAIL] 出站校验不可用（需要 $PY 与 $GUARD）—— fail-closed 停发"
  exit 1
fi

# 连接前：解析并校验目标主机（所有地址必须是公网地址）。
if ! target="$("$PY" -I "$GUARD" resolve "$URL" 2>&1)"; then
  fail "$URL 出站被拒（SEC-A2）：$target"
fi
read -r host port ip <<<"$target"
D_HOST="$host"; D_IP="$ip"
if "$PY" -I "$GUARD" exempt "$host"; then
  D_EXEMPT=1
  echo "[egress] $host 经 QA_EGRESS_ALLOW_HOSTS 豁免非公网检查（仅限测试）"
fi

# 钉住已校验的地址；IP 字面量主机本身就是连接地址，无需 --resolve。
resolve_arg=()
case "$host" in
  *:*|[0-9]*.[0-9]*.[0-9]*.[0-9]*) ;;
  *) case "$ip" in *:*) resolve_arg=(--resolve "$host:$port:[$ip]") ;; *) resolve_arg=(--resolve "$host:$port:$ip") ;; esac ;;
esac

# 不加 -L：规范地址本身就应返回 200，重定向说明地址或配置变了，需要人看。
out="$(curl -sS -o /dev/null -w '%{http_code} %{remote_ip}' --proto '=http,https' --noproxy '*' \
  "${resolve_arg[@]}" --max-time "$TIMEOUT" --retry 2 --retry-delay 2 "$URL" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ]; then
  fail "$URL 请求失败（curl 退出码 $rc）：$out"
fi
code="${out%% *}"; remote="${out#* }"
D_CODE="$code"; D_REMOTE="$remote"
# 连接后：核对实际连接地址（防 DNS 重绑定与 --resolve 未生效）。
if [ "${#resolve_arg[@]}" -gt 0 ] && [ "$remote" != "$ip" ]; then
  fail "$URL 实际连接地址 $remote 与校验地址 $ip 不一致（SEC-A2）"
fi
if ! "$PY" -I "$GUARD" verify "$host" "$remote"; then
  fail "$URL 实际连接地址 $remote 不是公网地址（SEC-A2）"
fi
if [ "$code" != "200" ]; then
  fail "$URL 返回 HTTP $code（要求 200）"
fi
echo "[PASS] $URL 返回 HTTP 200"
