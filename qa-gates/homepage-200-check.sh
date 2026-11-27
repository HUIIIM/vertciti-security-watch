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
GUARD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/egress_guard.py"

if ! command -v "$PY" >/dev/null 2>&1 || [ ! -f "$GUARD" ]; then
  echo "[FAIL] 出站校验不可用（需要 $PY 与 $GUARD）—— fail-closed 停发"
  exit 1
fi

# 连接前：解析并校验目标主机（所有地址必须是公网地址）。
if ! target="$("$PY" -I "$GUARD" resolve "$URL" 2>&1)"; then
  echo "[FAIL] $URL 出站被拒（SEC-A2）：$target"
  exit 1
fi
read -r host port ip <<<"$target"
if "$PY" -I "$GUARD" exempt "$host"; then
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
  echo "[FAIL] $URL 请求失败（curl 退出码 $rc）：$out"
  exit 1
fi
code="${out%% *}"; remote="${out#* }"
# 连接后：核对实际连接地址（防 DNS 重绑定与 --resolve 未生效）。
if [ "${#resolve_arg[@]}" -gt 0 ] && [ "$remote" != "$ip" ]; then
  echo "[FAIL] $URL 实际连接地址 $remote 与校验地址 $ip 不一致（SEC-A2）"
  exit 1
fi
if ! "$PY" -I "$GUARD" verify "$host" "$remote"; then
  echo "[FAIL] $URL 实际连接地址 $remote 不是公网地址（SEC-A2）"
  exit 1
fi
if [ "$code" != "200" ]; then
  echo "[FAIL] $URL 返回 HTTP $code（要求 200）"
  exit 1
fi
echo "[PASS] $URL 返回 HTTP 200"
