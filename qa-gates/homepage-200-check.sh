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
# 退出码: 0=PASS(200)  1=FAIL(非 200 / 连接失败 / 超时)
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

# 不加 -L：规范地址本身就应返回 200，重定向说明地址或配置变了，需要人看。
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" --retry 2 --retry-delay 2 "$URL" 2>&1)"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "[FAIL] $URL 请求失败（curl 退出码 $rc）：$code"
  exit 1
fi
if [ "$code" != "200" ]; then
  echo "[FAIL] $URL 返回 HTTP $code（要求 200）"
  exit 1
fi
echo "[PASS] $URL 返回 HTTP 200"
