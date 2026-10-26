#!/usr/bin/env bash
# data-room 发布门禁：发布前必跑。FAIL=停发，WARN=人工复核。
# 目标目录经位置参数或环境变量 DATA_ROOM_DIR 显式指定，无内置默认（早期版本
# 曾默认指向维护者本机已退役的检出路径，已参数化）；allowlist 按脚本同目录相对
# 解析、随脚本分发，不可读即 fail-closed 停发（早期固定为机器专属绝对路径，
# 不可达时 grep -f 报错被管道吞掉、检查空转假过 PASS，已修复）。
# 用法：bash data-room-gate.sh [data-room目录]
set -u
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "用法: bash data-room-gate.sh [--help] [data-room目录]"
  echo "  发布前必跑门禁：FAIL=停发，WARN=人工复核。"
  echo "  [data-room目录] 经位置参数或环境变量 DATA_ROOM_DIR 指定，无默认；未指定即报错退出。"
  exit 0
fi
DIR="${1:-${DATA_ROOM_DIR:-}}"
if [ -z "$DIR" ]; then
  echo "GATE FAIL: 未指定 data-room 目录（位置参数或环境变量 DATA_ROOM_DIR）" >&2
  exit 2
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALLOWLIST_SRC="$SCRIPT_DIR/gate-allowlist.txt"
FAIL=0; WARN=0

[ -d "$DIR" ] || { echo "GATE FAIL: 目录不存在 $DIR"; exit 1; }
# allowlist 随脚本同目录分发（相对脚本位置解析，不依赖机器专属路径）。
# fail-closed：allowlist 不可读即 FAIL 停发，禁止在过滤器失效状态下扫描。
[ -f "$ALLOWLIST_SRC" ] || touch "$ALLOWLIST_SRC" 2>/dev/null
{ [ -f "$ALLOWLIST_SRC" ] && [ -r "$ALLOWLIST_SRC" ]; } || { echo "GATE FAIL: allowlist 不可读 $ALLOWLIST_SRC —— 拒绝在过滤器缺失状态下扫描"; exit 1; }
# 生效副本剔除空行/空白行：空行作为 grep -F 模式会匹配每一行，造成整表假过滤（假过）。
ALLOWLIST="$(mktemp)"
trap 'rm -f "$ALLOWLIST"' EXIT
grep -v -e '^[[:space:]]*$' "$ALLOWLIST_SRC" > "$ALLOWLIST" || true

say_fail() { echo "GATE FAIL: $1"; FAIL=1; }
say_warn() { echo "GATE WARN: $1"; WARN=1; }

# 1. 绝密关键词：2027-02（硬红线，任何上下文都不行）
if grep -rIn --include='*.txt' -E '2027-0?2' "$DIR" | grep -v -F -f "$ALLOWLIST" | grep -q .; then
  say_fail "命中 2027-02 相关内容："
  grep -rIn --include='*.txt' -E '2027-0?2' "$DIR" | grep -v -F -f "$ALLOWLIST" | head -5
fi

# 2. 绝密/机密字样（排除文件头 Classification: Public 这类标注行）
if grep -rIn --include='*.txt' -E '绝密|机密|SECRET|TOP ?SECRET' "$DIR" | grep -v -i 'classification' | grep -v -F -f "$ALLOWLIST" | grep -q .; then
  say_fail "命中 绝密/机密 字样（非 Classification 标注）："
  grep -rIn --include='*.txt' -E '绝密|机密|SECRET|TOP ?SECRET' "$DIR" | grep -v -i 'classification' | grep -v -F -f "$ALLOWLIST" | head -5
fi

# 3. 私钥块
if grep -rIn --include='*.txt' -E -- '-----BEGIN .*PRIVATE KEY-----' "$DIR" | grep -q .; then
  say_fail "命中私钥块："
  grep -rIn --include='*.txt' -E -- '-----BEGIN .*PRIVATE KEY-----' "$DIR" | head -5
fi

# 4. 高置信 token 前缀（GitHub PAT / Stripe live / AWS / Slack）
if grep -rInE --include='*.txt' 'ghp_[A-Za-z0-9]{8,}|gho_[A-Za-z0-9]{8,}|sk_live_[A-Za-z0-9]{8,}|rk_live_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|xox[bap]-[A-Za-z0-9-]{8,}' "$DIR" | grep -v -F -f "$ALLOWLIST" | grep -q .; then
  say_fail "命中疑似密钥 token："
  grep -rInE --include='*.txt' 'ghp_[A-Za-z0-9]{8,}|gho_[A-Za-z0-9]{8,}|sk_live_[A-Za-z0-9]{8,}|rk_live_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|xox[bap]-[A-Za-z0-9-]{8,}' "$DIR" | grep -v -F -f "$ALLOWLIST" | sed -E 's/(ghp_|gho_|sk_live_|rk_live_|AKIA|xox[bap]-)[A-Za-z0-9-]{4}.*/\1****/' | head -5
fi

# 5. 口令赋值（疑似明文口令，WARN 级：可能是文档示例）
if grep -rIn --include='*.txt' -E -i '(password|passwd|pwd)\s*[:=]\s*["'"'"']?[^"'"'"' ]{6,}' "$DIR" | grep -v -i -E 'password (requirement|policy|must|should)|your password|no password|passwordless' | grep -v -F -f "$ALLOWLIST" | grep -q .; then
  say_warn "命中疑似口令赋值（请人工确认是否为示例）："
  grep -rIn --include='*.txt' -E -i '(password|passwd|pwd)\s*[:=]\s*["'"'"']?[^"'"'"' ]{6,}' "$DIR" | grep -v -i -E 'password (requirement|policy|must|should)|your password|no password|passwordless' | grep -v -F -f "$ALLOWLIST" | cut -c1-100 | head -5
fi

# 6. 邮箱地址（WARN 级：公开文件原则上不出现个人邮箱）
if grep -rIno --include='*.txt' -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$DIR" | grep -v -F -f "$ALLOWLIST" | grep -q .; then
  say_warn "命中邮箱地址（请确认是否为应公开的联系邮箱）："
  grep -rIno --include='*.txt' -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$DIR" | grep -v -F -f "$ALLOWLIST" | head -5
fi

echo "---- 扫描文件数：$(find "$DIR" -name '*.txt' | wc -l) ----"
if [ "$FAIL" -eq 1 ]; then echo "结果：FAIL —— 停止发布，整改后重跑"; exit 1; fi
if [ "$WARN" -eq 1 ]; then echo "结果：WARN —— 可发布，但请 GC 复核上述项"; exit 0; fi
echo "结果：PASS"
