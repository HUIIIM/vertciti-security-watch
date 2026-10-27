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
DIR="$(cd "$DIR" && pwd)"  # 规范化为绝对路径（去掉末尾 /），allowlist 的相对路径据此计算
# allowlist 随脚本同目录分发（相对脚本位置解析，不依赖机器专属路径）。
# fail-closed：allowlist 不可读即 FAIL 停发，禁止在过滤器失效状态下扫描。
[ -f "$ALLOWLIST_SRC" ] || touch "$ALLOWLIST_SRC" 2>/dev/null
{ [ -f "$ALLOWLIST_SRC" ] && [ -r "$ALLOWLIST_SRC" ]; } || { echo "GATE FAIL: allowlist 不可读 $ALLOWLIST_SRC —— 拒绝在过滤器缺失状态下扫描"; exit 1; }
# allowlist 条目格式（见 gate-allowlist.txt 文件头）：
#   相对路径:行号   放行该文件这一行的命中
#   相对路径:*      放行整个文件（人工复核过的二进制文件、整份示例文档）
# 按"路径:行号"精确比对，不做子串匹配：只写文件名不会放行任何东西；
# 空行与 # 注释行忽略（空行作为子串模式会放行一切）。
ALLOWLIST="$ALLOWLIST_SRC"

say_fail() { echo "GATE FAIL: $1"; FAIL=1; }
say_warn() { echo "GATE WARN: $1"; WARN=1; }

# 未被 allowlist 放行的命中，输出 "相对路径:行号:内容"。参数原样传给 grep（-E 正则、可加 -i/-o）。
hits() {
  ( cd "$DIR" && grep -rIn "$@" . 2>/dev/null ) | sed 's#^\./##' | awk -F: -v al="$ALLOWLIST" '
    FILENAME == al { if ($0 !~ /^[[:space:]]*(#|$)/) { sub(/[[:space:]]+$/, ""); ok[$0] = 1 } next }
    !((($1 ":" $2) in ok) || (($1 ":*") in ok))
  ' "$ALLOWLIST" -
}

# 命中只报位置（路径:行号），不回显内容：门禁输出会进 CI / 部署日志，回显即二次泄露。
report() { cut -d: -f1,2 | head -5; }

# 0. 覆盖面：所有文件都要能被扫描。不可读文件、无法按文本扫描的二进制文件（PDF/DOCX/图片等）
#    一律 FAIL，人工复核后以 "路径:*" 登记 allowlist 放行；扫描文件数为 0 也 FAIL。
NFILES=0; UNSCANNABLE=""
while IFS= read -r -d '' f; do
  NFILES=$((NFILES + 1))
  rel="${f#"$DIR"/}"
  if [ ! -r "$f" ]; then
    UNSCANNABLE="$UNSCANNABLE$rel:不可读"$'\n'
  elif [ -s "$f" ] && ! grep -qI '' "$f"; then
    UNSCANNABLE="$UNSCANNABLE$rel:二进制"$'\n'
  fi
done < <(find "$DIR" -type f -print0)
if [ "$NFILES" -eq 0 ]; then
  say_fail "目录内没有任何文件，拒绝在空扫描下报 PASS：$DIR"
fi
UNSCANNABLE="$(printf '%s' "$UNSCANNABLE" | awk -F: -v al="$ALLOWLIST" '
  FILENAME == al { if ($0 !~ /^[[:space:]]*(#|$)/) { sub(/[[:space:]]+$/, ""); ok[$0] = 1 } next }
  !(($1 ":*") in ok)
' "$ALLOWLIST" -)"
if [ -n "$UNSCANNABLE" ]; then
  say_fail "存在无法按文本扫描的文件（人工复核后以 路径:* 登记 allowlist）："
  printf '%s\n' "$UNSCANNABLE" | head -5
fi

# 1. 绝密关键词：2027-02（硬红线，任何上下文都不行；含 2027/02、2027.02、2027年2月、Feb 2027 等写法）
if hits -E -i '2027[-/.][[:space:]]*0?2|2027[[:space:]]*年[[:space:]]*0?2[[:space:]]*月|feb(ruary)?\.?[[:space:]]*2027' | grep -q .; then
  say_fail "命中 2027-02 相关内容："
  hits -E -i '2027[-/.][[:space:]]*0?2|2027[[:space:]]*年[[:space:]]*0?2[[:space:]]*月|feb(ruary)?\.?[[:space:]]*2027' | report
fi

# 2. 绝密/机密字样（不再按 "classification" 整行豁免：标注为 TOP SECRET 的文件本身就该停发；
#    "Classification: Public" 这类标注行本就不含这些字样，不受影响）
if hits -E '绝密|机密|SECRET' | grep -q .; then
  say_fail "命中 绝密/机密 字样："
  hits -E '绝密|机密|SECRET' | report
fi

# 3. 私钥块（不经 allowlist）
if ( cd "$DIR" && grep -rIn -E -- '-----BEGIN .*PRIVATE KEY-----' . 2>/dev/null ) | grep -q .; then
  say_fail "命中私钥块："
  ( cd "$DIR" && grep -rIn -E -- '-----BEGIN .*PRIVATE KEY-----' . 2>/dev/null ) | sed 's#^\./##' | report
fi

# 4. 高置信 token 前缀（GitHub PAT/OAuth/App / Stripe live / AWS / Slack / Anthropic / Google API key）
TOKEN_RE='gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{20,}|sk_live_[A-Za-z0-9]{8,}|rk_live_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}|xox[bap]-[A-Za-z0-9-]{8,}|sk-ant-[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{35}'
if hits -E "$TOKEN_RE" | grep -q .; then
  say_fail "命中疑似密钥 token："
  hits -E "$TOKEN_RE" | report
fi

# 5. 口令赋值（疑似明文口令，WARN 级：可能是文档示例）
PW_RE='(password|passwd|pwd)[[:space:]]*[:=][[:space:]]*["'"'"']?[^"'"'"' ]{6,}'
PW_EXCLUDE='password (requirement|policy|must|should)|your password|no password|passwordless'
if hits -E -i "$PW_RE" | grep -v -i -E "$PW_EXCLUDE" | grep -q .; then
  say_warn "命中疑似口令赋值（请人工确认是否为示例）："
  hits -E -i "$PW_RE" | grep -v -i -E "$PW_EXCLUDE" | report
fi

# 6. 邮箱地址（WARN 级：公开文件原则上不出现个人邮箱；邮箱本身需人工判断，故回显）
if hits -o -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' | grep -q .; then
  say_warn "命中邮箱地址（请确认是否为应公开的联系邮箱）："
  hits -o -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' | head -5
fi

echo "---- 扫描文件数：$NFILES ----"
if [ "$FAIL" -eq 1 ]; then echo "结果：FAIL —— 停止发布，整改后重跑"; exit 1; fi
if [ "$WARN" -eq 1 ]; then echo "结果：WARN —— 可发布，但请 GC 复核上述项"; exit 0; fi
echo "结果：PASS"
