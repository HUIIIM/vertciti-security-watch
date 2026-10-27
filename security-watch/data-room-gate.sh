#!/usr/bin/env bash
# data-room 发布门禁（门禁 1，双层形态）：发布前必跑。FAIL=停发，WARN=人工复核。
# 目标目录经位置参数或环境变量 DATA_ROOM_DIR 显式指定，无内置默认（早期版本
# 曾默认指向维护者本机已退役的检出路径，已参数化）；allowlist 按脚本同目录相对
# 解析、随脚本分发，不可读即 fail-closed 停发（早期固定为机器专属绝对路径，
# 不可达时 grep -f 报错被管道吞掉、检查空转假过 PASS，已修复）。
# 2026-10-26 (issue #6) fail-closed 补强与输出脱敏：
#   - set -o pipefail；每条检查区分 grep 退出码（0=有命中 / 1=无命中 / >=2=
#     扫描出错），出错即 FAIL 停发，不再把错误当无命中放行；
#   - allowlist 缺失即 FAIL（不再自动创建空文件）；生效条目剔除空行与 # 注释行；
#   - 目标目录内可扫描 .txt 文件数为 0 即 FAIL，禁止真空通过；
#   - allowlist 改精确匹配（废止整行子串匹配：一个空行/短条目曾可放行一切）：
#     条目格式为 <相对路径>:<行号>:<该行精确内容>，或 fp:<sha256(相对路径:行号:内容)>；
#     相对路径以被扫描目录为根。文件被编辑、行号或内容变化后条目自动失效，
#     命中重新浮现，须按新实例重新登记——这是有意的 fail-closed 语义；
#   - 命中输出默认脱敏：只出 文件:行号 与掩码/指纹，口令、连接串、token 与
#     敏感正文的明文零出 stdout。GATE_SHOW_CONTENT=1 可显式改为输出原文，
#     仅限本机人工复核，禁止在 CI/日志留存环境开启（明文会进日志）。
# 2026-10-27 (issue #5) 覆盖面补强：
#   - 扫描目录内全部普通文件，不再只扫 *.txt（.md/.json/.html/.csv/.pem 等此前完全不扫）；
#   - 无法按文本扫描的二进制文件（PDF/DOCX/图片等）一律 FAIL，人工复核后以
#     bin:<相对路径>:<sha256(文件)> 登记 allowlist 放行（文件变化后条目自动失效）；
#   - 不再按 "classification" 整行豁免规则 2 字样（标注为最高密级的行本身就该停发）；
#   - 规则 1 覆盖封存日期的多种写法变体；规则 4 增加 github_pat_、ghs_/ghu_/ghr_、
#     sk-ant-、AIza 等 token 前缀。
# 2026-10-27 (GC-20261027-002) 模式集双层化（判据内容不变，只动存放与装载形态）：
#   - 六条规则的模式串不再内嵌脚本。仓内随脚本分发的是结构骨架
#     gate-patterns-skeleton.txt（真合成模式，供结构测试与非约束性运行，
#     它不是完整门禁）；具约束力的全量模式集存放于部署侧私有面，发布运行经
#     环境变量 GATE_PATTERN_FILE 装载，并先按登记指纹验真——指纹经
#     GATE_PATTERN_SHA256 或 GATE_PATTERN_FP_FILE（指纹登记文件）提供，
#     缺失或不符即 fail-closed 停发，不回退骨架作约束判定；
#   - 未指定 GATE_PATTERN_FILE 时为骨架运行，输出显式标注「非约束性」。
# 2026-10-27 (issue #5 复核) 骨架运行不得以 0 退出：骨架的规则 1/2 是合成占位模式，
#   真实封存内容在骨架下不会命中；若仍以 PASS/exit 0 结束，漏设 GATE_PATTERN_FILE 的
#   发布流水线会把它当成放行（按 README 快速开始原样运行即是此路径）。现骨架运行
#   无 FAIL 时以 exit 3「NON-BINDING」结束；本地调试/测试须显式设 GATE_ALLOW_SKELETON=1
#   才恢复 0。命中 FAIL 仍为 exit 1（骨架的私钥/token 等规则是真实模式）。
# 用法：bash data-room-gate.sh [data-room目录]
set -u
set -o pipefail
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  echo "用法: bash data-room-gate.sh [--help] [data-room目录]"
  echo "  发布前必跑门禁（双层形态）：FAIL=停发，WARN=人工复核。"
  echo "  [data-room目录] 经位置参数或环境变量 DATA_ROOM_DIR 指定，无默认；未指定即报错退出。"
  echo "  allowlist: 脚本同目录 gate-allowlist.txt，条目为 <相对路径>:<行号>:<精确内容> 或 fp:<sha256>，精确匹配。"
  echo "  二进制文件（无法按文本扫描）默认 FAIL；人工复核后以 bin:<相对路径>:<sha256(文件)> 放行。"
  echo "  模式集: 默认装载脚本同目录 gate-patterns-skeleton.txt（骨架，合成模式，非约束性运行）；"
  echo "    约束性运行须 GATE_PATTERN_FILE=<部署侧全量模式集> 且 GATE_PATTERN_SHA256=<登记指纹>"
  echo "    （或 GATE_PATTERN_FP_FILE=<指纹登记文件>），指纹不符即停发。"
  echo "  骨架运行无 FAIL 时以 exit 3（NON-BINDING）结束，不是放行；GATE_ALLOW_SKELETON=1 仅供本地/测试恢复 exit 0。"
  echo "  命中输出默认脱敏；GATE_SHOW_CONTENT=1 输出原文（仅限本机人工复核，禁止在 CI 开启）。"
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

WORK_TMP="$(mktemp -d)"
trap 'rm -rf "$WORK_TMP"' EXIT
RAW="$WORK_TMP/raw"; RAW2="$WORK_TMP/raw2"; KEPT="$WORK_TMP/kept"; EFF="$WORK_TMP/allowlist.eff"

[ -d "$DIR" ] || { echo "GATE FAIL: 目录不存在 $DIR"; exit 1; }
# allowlist 随脚本同目录分发（相对脚本位置解析，不依赖机器专属路径）。
# fail-closed：allowlist 缺失/不可读即 FAIL 停发，禁止在过滤器失效状态下扫描。
{ [ -f "$ALLOWLIST_SRC" ] && [ -r "$ALLOWLIST_SRC" ]; } || { echo "GATE FAIL: allowlist 缺失或不可读 $ALLOWLIST_SRC —— 拒绝在过滤器缺失状态下扫描"; exit 1; }
# 生效条目剔除空行/空白行与 # 注释行：空行作为模式会匹配每一行，造成整表假过滤（假过）。
grep -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' "$ALLOWLIST_SRC" > "$EFF"
GRC=$?
if [ "$GRC" -ge 2 ]; then echo "GATE FAIL: allowlist 读取错误 $ALLOWLIST_SRC —— fail-closed 停发"; exit 1; fi

# ---- 模式集装载（双层形态，GC-20261027-002）----
# 模式集行格式：<规则>.<字段> <模式（至行尾）>；字段 pattern / exclude（仅规则 5）。
# 骨架（默认）：脚本同目录 gate-patterns-skeleton.txt，合成模式，非约束性运行。
# 全量集：GATE_PATTERN_FILE 指定部署侧私有文件，运行前必须验指纹。
PATTERN_SRC="${GATE_PATTERN_FILE:-$SCRIPT_DIR/gate-patterns-skeleton.txt}"
{ [ -f "$PATTERN_SRC" ] && [ -r "$PATTERN_SRC" ]; } || { echo "GATE FAIL: 模式集缺失或不可读 $PATTERN_SRC —— fail-closed 停发"; exit 1; }
if [ -n "${GATE_PATTERN_FILE:-}" ]; then
  FP_EXPECTED="${GATE_PATTERN_SHA256:-}"
  if [ -z "$FP_EXPECTED" ] && [ -n "${GATE_PATTERN_FP_FILE:-}" ]; then
    FP_EXPECTED="$(tr -d '[:space:]' < "$GATE_PATTERN_FP_FILE" 2>/dev/null || true)"
  fi
  if [ -z "$FP_EXPECTED" ]; then
    echo "GATE FAIL: 全量模式集运行未提供登记指纹（GATE_PATTERN_SHA256 或 GATE_PATTERN_FP_FILE）—— fail-closed 停发"; exit 1
  fi
  FP_ACTUAL="$(sha256sum "$PATTERN_SRC" | cut -d' ' -f1)"
  if [ "$FP_ACTUAL" != "$FP_EXPECTED" ]; then
    echo "GATE FAIL: 模式集指纹不符（登记 ${FP_EXPECTED:0:8}… / 实测 ${FP_ACTUAL:0:8}…）—— fail-closed 停发，不作约束判定"; exit 1
  fi
  echo "模式集：全量集（部署侧），指纹验真通过（sha256 ${FP_ACTUAL:0:8}…）"
else
  echo "模式集：仓内骨架（合成模式）—— 非约束性运行，判定不作发布依据"
fi
PAT1=""; PAT2=""; PAT3=""; PAT4=""; PAT5=""; PAT5X=""; PAT6=""
while IFS= read -r pline || [ -n "$pline" ]; do
  case "$pline" in ''|'#'*) continue ;; esac
  pkey="${pline%% *}"; pval="${pline#* }"
  case "$pkey" in
    1.pattern) PAT1="$pval" ;;
    2.pattern) PAT2="$pval" ;;
    3.pattern) PAT3="$pval" ;;
    4.pattern) PAT4="$pval" ;;
    5.pattern) PAT5="$pval" ;;
    5.exclude) PAT5X="$pval" ;;
    6.pattern) PAT6="$pval" ;;
    *) echo "GATE FAIL: 模式集含未知条目 $pkey —— fail-closed 停发"; exit 1 ;;
  esac
done < "$PATTERN_SRC"
if [ -z "$PAT1" ] || [ -z "$PAT2" ] || [ -z "$PAT3" ] || [ -z "$PAT4" ] || [ -z "$PAT5" ] || [ -z "$PAT5X" ] || [ -z "$PAT6" ]; then
  echo "GATE FAIL: 模式集不完整（六规则模式与规则 5 排除清单须齐全）—— fail-closed 停发"; exit 1
fi

# 扫描文件数：只计普通文件（grep -r 不跟随扫描树内符号链接，计数口径与实际扫描一致）。
if ! find "$DIR" -type f -print0 > "$WORK_TMP/files" 2>/dev/null; then
  echo "GATE FAIL: 枚举目标文件失败 —— fail-closed 停发"; exit 1
fi
FILE_COUNT="$(tr -cd '\0' < "$WORK_TMP/files" | wc -c)"
if [ "$FILE_COUNT" -eq 0 ]; then
  echo "GATE FAIL: 目标目录内文件数为 0 —— 拒绝真空通过"; exit 1
fi

say_fail() { echo "GATE FAIL: $1"; FAIL=1; }
say_warn() { echo "GATE WARN: $1"; WARN=1; }
scan_error() { echo "GATE FAIL: $1 扫描过程出错（grep 退出码 $2）—— fail-closed 停发"; FAIL=1; }

# 0. 二进制文件：grep -I 会静默跳过，等于没扫。非空且无法按文本读取的文件一律 FAIL，
#    除非 allowlist 有与当前文件内容绑定的 bin:<相对路径>:<sha256> 条目。
#    （不可读文件由下方各规则的 grep 退出码 >=2 判 FAIL。）
: > "$WORK_TMP/binary"
while IFS= read -r -d '' f; do
  [ -r "$f" ] && [ -s "$f" ] || continue
  if ! grep -qI '' "$f"; then
    rel="${f#"$DIR"/}"
    sum="$(sha256sum "$f" | cut -d' ' -f1)"
    grep -qxF "bin:$rel:$sum" "$EFF" || echo "$rel: [二进制，无法按文本扫描 sha256=$sum]" >> "$WORK_TMP/binary"
  fi
done < "$WORK_TMP/files"
if [ -s "$WORK_TMP/binary" ]; then
  say_fail "存在无法按文本扫描的文件（人工复核后以 bin:<相对路径>:<sha256> 登记 allowlist）："
  head -5 "$WORK_TMP/binary"
fi

# collect: 运行一次 grep，结果落 RAW；GRC 保存退出码（0=有命中 1=无命中 >=2=出错）。
collect() {
  grep "$@" > "$RAW"
  GRC=$?
  return 0
}
# refilter: 以 grep -v 类过滤器对 RAW 再过滤（规则自带的内容排除，判定口径不变）。
refilter() {
  grep "$@" "$RAW" > "$RAW2"
  GRC=$?
  if [ "$GRC" -ge 2 ]; then return 1; fi
  mv "$RAW2" "$RAW"
  return 0
}
# is_exempt <相对路径> <行号> <内容>：与生效条目精确比对（字面条目或 fp: 指纹条目）。
is_exempt() {
  local rel="$1" lineno="$2" content="$3" entry fp
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    if [ "$entry" = "$rel:$lineno:$content" ]; then return 0; fi
    case "$entry" in
      fp:*)
        fp="$(printf '%s' "$rel:$lineno:$content" | sha256sum | cut -d' ' -f1)"
        if [ "$entry" = "fp:$fp" ]; then return 0; fi
        ;;
    esac
  done < "$EFF"
  return 1
}
# apply_allowlist: RAW -> KEPT，仅剔除被精确条目豁免的命中。
apply_allowlist() {
  : > "$KEPT"
  local line path lineno content rel
  while IFS= read -r line; do
    if [[ "$line" =~ ^(.*):([0-9]+):(.*)$ ]]; then
      path="${BASH_REMATCH[1]}"; lineno="${BASH_REMATCH[2]}"; content="${BASH_REMATCH[3]}"
      rel="${path#"$DIR"/}"
      if is_exempt "$rel" "$lineno" "$content"; then continue; fi
    fi
    echo "$line" >> "$KEPT"
  done < "$RAW"
}
# print_hits <模式 redact|assign|email>：打印 KEPT 前 5 条，默认脱敏。
print_hits() {
  local mode="$1" line path lineno content len fp8 n=0
  while IFS= read -r line && [ "$n" -lt 5 ]; do
    n=$((n + 1))
    if [ "${GATE_SHOW_CONTENT:-0}" = "1" ]; then echo "$line"; continue; fi
    if [[ "$line" =~ ^(.*):([0-9]+):(.*)$ ]]; then
      path="${BASH_REMATCH[1]}"; lineno="${BASH_REMATCH[2]}"; content="${BASH_REMATCH[3]}"
    else
      echo "$line"; continue
    fi
    case "$mode" in
      assign)
        printf '%s:%s:%s\n' "$path" "$lineno" "$(printf '%s' "$content" | sed -E -e 's#(://[^:/@ ]+:)[^@ ]+@#\1****@#g' -e "s/((password|passwd|pwd)[[:space:]]*[:=][[:space:]]*[\"']?)[^\"' ]+/\\1****/i")"
        ;;
      email)
        printf '%s:%s:%s\n' "$path" "$lineno" "$(printf '%s' "$content" | sed -E 's/([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/\1****\2/g')"
        ;;
      *)
        len="$(printf '%s' "$content" | wc -c)"
        fp8="$(printf '%s' "$content" | sha256sum | cut -c1-8)"
        printf '%s:%s: [内容已脱敏 len=%s fp=%s]\n' "$path" "$lineno" "$len" "$fp8"
        ;;
    esac
  done < "$KEPT"
}

# 1. 封存日期（硬红线，任何上下文都不行；写法变体见模式集规则 1）
collect -rIn -i -E "$PAT1" "$DIR"
if [ "$GRC" -ge 2 ]; then
  scan_error "规则1（封存日期）" "$GRC"
elif [ "$GRC" -eq 0 ]; then
  apply_allowlist
  if [ -s "$KEPT" ]; then
    say_fail "命中规则 1（封存日期类）内容："
    print_hits redact
  fi
fi

# 2. 停发字样（不按 "classification" 整行豁免：标注为最高密级的行本身就该停发；
#    "Classification: Public" 这类标注行本就不含这些字样，不受影响）
collect -rIn -E "$PAT2" "$DIR"
if [ "$GRC" -ge 2 ]; then
  scan_error "规则2（停发字样）" "$GRC"
elif [ "$GRC" -eq 0 ]; then
  apply_allowlist
  if [ -s "$KEPT" ]; then
    say_fail "命中规则 2（停发字样）："
    print_hits redact
  fi
fi

# 3. 私钥块
collect -rIn -E -- "$PAT3" "$DIR"
if [ "$GRC" -ge 2 ]; then
  scan_error "规则3（私钥块）" "$GRC"
elif [ "$GRC" -eq 0 ]; then
  cp "$RAW" "$KEPT"
  say_fail "命中私钥块："
  print_hits redact
fi

# 4. 高置信 token 前缀（GitHub PAT/OAuth/App / Stripe live / AWS / Slack / Anthropic / Google API key）
collect -rIn -E "$PAT4" "$DIR"
if [ "$GRC" -ge 2 ]; then
  scan_error "规则4（token）" "$GRC"
elif [ "$GRC" -eq 0 ]; then
  apply_allowlist
  if [ -s "$KEPT" ]; then
    say_fail "命中疑似密钥 token："
    print_hits redact
  fi
fi

# 5. 口令赋值（疑似明文口令，WARN 级：可能是文档示例）
collect -rIn -E -i "$PAT5" "$DIR"
if [ "$GRC" -ge 2 ]; then
  scan_error "规则5（口令赋值）" "$GRC"
elif [ "$GRC" -eq 0 ]; then
  if ! refilter -v -i -E "$PAT5X"; then
    scan_error "规则5（口令赋值）" "$GRC"
  else
    apply_allowlist
    if [ -s "$KEPT" ]; then
      say_warn "命中疑似口令赋值（请人工确认是否为示例）："
      print_hits assign
    fi
  fi
fi

# 6. 邮箱地址（WARN 级：公开文件原则上不出现个人邮箱）
collect -rIno -E "$PAT6" "$DIR"
if [ "$GRC" -ge 2 ]; then
  scan_error "规则6（邮箱）" "$GRC"
elif [ "$GRC" -eq 0 ]; then
  apply_allowlist
  if [ -s "$KEPT" ]; then
    say_warn "命中邮箱地址（请确认是否为应公开的联系邮箱）："
    print_hits email
  fi
fi

echo "---- 扫描文件数：$FILE_COUNT ----"
if [ "$FAIL" -eq 1 ]; then echo "结果：FAIL —— 停止发布，整改后重跑"; exit 1; fi
if [ -z "${GATE_PATTERN_FILE:-}" ] && [ "${GATE_ALLOW_SKELETON:-0}" != "1" ]; then
  echo "结果：NON-BINDING —— 仓内骨架运行，未装载全量模式集，不能作为放行依据（exit 3）。"
  echo "  发布运行须设 GATE_PATTERN_FILE + 指纹；仅本地调试/测试可设 GATE_ALLOW_SKELETON=1。"
  exit 3
fi
if [ "$WARN" -eq 1 ]; then echo "结果：WARN —— 可发布，但请 GC 复核上述项"; exit 0; fi
echo "结果：PASS"
