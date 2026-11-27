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
# 2026-10-27 模式集双层化（判据内容不变，只动存放与装载形态）：
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
# 2026-10-28 (#6 OPS-2) 机器可读运行记录：设 GATE_JSON_OUT=<路径> 时，每次运行（含中途
#   fail-closed 退出）结束都写一份 JSON：结果与退出码、模式集形态与 sha256、allowlist 与
#   脚本 sha256、被扫文件清单指纹（相对路径+文件 sha256，排序后再取 sha256），以及每条
#   命中的 规则/级别/相对路径/行号——只有位置，不含任何命中内容。要求了记录却写不出来
#   （如缺 python3）即 exit 1，不让流水线在缺证据时放行。
# 2026-11-20 (#6 评分卡 门禁 1 批次 1) 退出码契约、规则 4 补全、记录/指纹加固：
#   - 退出码契约（调用方据此区分，不得把非 0 一律当失败、也不得把 0 与 4 混同）：
#       exit 0  PASS         无任何命中，可放行（仅全量模式集运行；骨架运行见 3）
#       exit 1  FAIL         FAIL 级命中或任一 fail-closed 条件，停发
#       exit 2  USAGE        用法错误（未指定 data-room 目录）
#       exit 3  NON-BINDING  骨架运行（未装载全量模式集）且无 FAIL，不是放行依据
#       exit 4  WARN         仅有 WARN 级命中（口令赋值/邮箱），须人工复核后才可放行；
#                            此前 WARN 与 PASS 同为 0、不可区分
#     优先级：1 > 3 > 4 > 0（有 FAIL 即 1；无 FAIL 的骨架运行为 3，即便另有 WARN；其后才是 4/0）。
#     GATE_ALLOW_SKELETON=1 的本地/测试运行：无命中 0、仅 WARN 为 4。
#   - 规则 4 补 OpenAI sk-proj-、GitLab glpat-、npm_、JWT、aws_secret_access_key 赋值、
#     Stripe/Restricted *_test_、Twilio SK、SendGrid SG.、Slack webhook URL、
#     数据库连接串内联口令（postgres/mysql/mongodb/redis/amqp://用户:口令@）；
#   - 命中输出掩码不得保留任何凭据字符：URL/连接串 userinfo 口令一律整段掩码，
#     真实邮箱仍保留首字符（此前 postgres://u:Zebra9@h 输出 Z****@h，泄露口令首字符）；
#   - grep 输出改用 -Z（路径后接 NUL）解析，路径与行号不再因行内容形如 ref:2:… 或路径含 :数字: 而错位；
#   - 模式集严格校验（骨架与全量集同一检查）：每行必须是 "<规则>.<字段> <非空模式>"，六条规则的
#     pattern 与规则 5 exclude 须齐全且各出现且仅出现一次，缺空格/空值/重复/未知条目一律 exit 1
#     （此前只有 "1.pattern" 而无模式正文的行会把键名本身当作字面正则通过完整性检查）；
#   - 运行记录增加 run_id（UUIDv4）与 gate_version（本脚本版本，见 GATE_VERSION）；
#   - 命中指纹 fp 改为完整 64 位十六进制 SHA-256；设环境变量 GATE_FP_KEY 时改用以其为密钥的
#     HMAC-SHA256。allowlist 的 fp: 条目与输出指纹走同一函数（fp_hex）：设了密钥后，
#     只有按同一密钥算出的 fp: 条目才生效，无密钥算出的条目不再生效（须重新登记）。
#     残余风险：无 GATE_FP_KEY 时指纹仍是未加盐哈希，持日志者可对低熵行内容离线验证猜测
#     （全长只是不再可碰撞缩短，并不能阻止猜测）；密钥经进程环境传递，泄露即失效。
#     对低熵内容（日期、短口令）的日志留存环境应设置 GATE_FP_KEY 并将密钥与日志分开存放。
#   - [过渡标注，中枢 2026-11-20 裁定] 打印 fp 与 allowlist fp: 的哈希输入不同：打印 fp 哈希
#     「行内容」，allowlist fp: 哈希「相对路径:行号:内容」——两面语义不同、不可互比、不可互抄
#     （把打印 fp 抄进 allowlist 不会命中）。统一至「相对路径:行号:内容」并入批 2 与 ARCH-3
#     指纹重注册同批落码，落码后本标注删除。
# 用法：bash data-room-gate.sh [data-room目录]
GATE_VERSION="1.1.0"
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
  echo "  GATE_JSON_OUT=<路径>：结束时写机器可读运行记录（JSON，只含命中位置，不含内容）；写不出即 exit 1。"
  echo "  退出码: exit 0=PASS  exit 1=FAIL  exit 2=用法错误  exit 3=NON-BINDING(骨架)  exit 4=WARN(仅 WARN 级命中，须人工复核)"
  echo "  GATE_FP_KEY=<密钥>：命中指纹与 allowlist fp: 条目改用 HMAC-SHA256（缺省为未加盐 SHA-256，低熵内容可被离线猜测）。"
  echo "  注意（过渡标注）：打印 fp 哈希「行内容」、allowlist fp: 哈希「相对路径:行号:内容」，两面不可互比、不可互抄；统一口径将于批 2 落码。"
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
RAW="$WORK_TMP/raw"; RAW2="$WORK_TMP/raw2"; KEPT="$WORK_TMP/kept"; EFF="$WORK_TMP/allowlist.eff"
FINDINGS="$WORK_TMP/findings.tsv"; : > "$FINDINGS"   # 规则<TAB>级别<TAB>相对路径<TAB>行号，供运行记录

# write_record <退出码>：GATE_JSON_OUT 指定时写 JSON 运行记录；失败返回非 0。
write_record() {
  local rc="$1" result
  case "$rc" in
    0) result=PASS ;;
    4) result=WARN ;;
    1) result=FAIL ;;
    3) result=NON-BINDING ;;
    *) result=ERROR ;;
  esac
  command -v python3 >/dev/null 2>&1 || { echo "GATE FAIL: 要求写运行记录（GATE_JSON_OUT）但缺少 python3" >&2; return 1; }
  python3 -I - "$GATE_JSON_OUT" "$rc" "$result" "$DIR" "${BASH_SOURCE[0]}" "$ALLOWLIST_SRC" \
      "${PATTERN_SRC:-}" "${GATE_PATTERN_FILE:+full}" "$WORK_TMP/files" "$FINDINGS" "$GATE_VERSION" <<'PY_EOF'
import datetime, hashlib, json, os, re, sys, uuid
out, rc, result, root, script, allowlist, patterns, mode, files, findings, version = sys.argv[1:12]

def unesc(s):
    return re.sub(r"\\(\\|n|t)", lambda m: {"\\": "\\", "n": "\n", "t": "\t"}[m.group(1)], s)

def sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None

manifest = []
if os.path.exists(files):
    for p in open(files, "rb").read().split(b"\0"):
        if p:
            p = p.decode("utf-8", "surrogateescape")
            manifest.append("%s\t%s" % (os.path.relpath(p, root), sha(p)))
manifest.sort()
hits = []
for row in open(findings, encoding="utf-8", errors="replace"):
    rule, severity, path, line = (row.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
    path = unesc(path)
    hits.append({"rule": rule, "severity": severity, "path": path or None,
                 "line": int(line) if line.isdigit() else None})
run_id = str(uuid.uuid4())
record = {
    "schema": "vertciti-data-room-gate/1",
    "run_id": run_id,
    # trace_id: GATE_TRACE_ID set by the release pipeline correlates gates 1-3 of one release (OPS-2)
    "trace_id": os.environ.get("GATE_TRACE_ID") or run_id,
    "gate": "data-room",
    "gate_version": version,
    "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "result": result,
    "exit_code": int(rc),
    "pattern_set": {"mode": mode or "skeleton", "sha256": sha(patterns) if patterns else None},
    "allowlist_sha256": sha(allowlist),
    "script_sha256": sha(script),
    "files_scanned": len(manifest),
    "files_manifest_sha256": hashlib.sha256("\n".join(manifest).encode()).hexdigest(),
    "findings": hits,
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=1)
    f.write("\n")
PY_EOF
}
on_exit() {
  local rc=$?
  if [ -n "${GATE_JSON_OUT:-}" ] && ! write_record "$rc"; then
    echo "GATE FAIL: 运行记录写入失败 $GATE_JSON_OUT —— fail-closed" >&2
    rc=1
  fi
  rm -rf "$WORK_TMP"
  exit "$rc"
}
trap on_exit EXIT

[ -d "$DIR" ] || { echo "GATE FAIL: 目录不存在 $DIR"; exit 1; }
# allowlist 随脚本同目录分发（相对脚本位置解析，不依赖机器专属路径）。
# fail-closed：allowlist 缺失/不可读即 FAIL 停发，禁止在过滤器失效状态下扫描。
{ [ -f "$ALLOWLIST_SRC" ] && [ -r "$ALLOWLIST_SRC" ]; } || { echo "GATE FAIL: allowlist 缺失或不可读 $ALLOWLIST_SRC —— 拒绝在过滤器缺失状态下扫描"; exit 1; }
# 生效条目剔除空行/空白行与 # 注释行：空行作为模式会匹配每一行，造成整表假过滤（假过）。
grep -v -e '^[[:space:]]*$' -e '^[[:space:]]*#' "$ALLOWLIST_SRC" > "$EFF"
GRC=$?
if [ "$GRC" -ge 2 ]; then echo "GATE FAIL: allowlist 读取错误 $ALLOWLIST_SRC —— fail-closed 停发"; exit 1; fi

# ---- 模式集装载（双层形态）----
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
# 严格装载（骨架与全量集同一检查）：每行须为 "<规则>.<字段> <非空模式>"，已知键各出现一次；
# 缺空格（键名本身会被当作字面正则）、空值、重复、未知条目一律 fail-closed。
pattern_bad() { echo "GATE FAIL: 模式集条目非法（$1）—— fail-closed 停发"; exit 1; }
while IFS= read -r pline || [ -n "$pline" ]; do
  case "$pline" in ''|'#'*) continue ;; esac
  case "$pline" in *" "*) ;; *) pattern_bad "缺少空格分隔的模式正文：$pline" ;; esac
  pkey="${pline%% *}"; pval="${pline#* }"
  [ -n "${pval//[[:space:]]/}" ] || pattern_bad "模式正文为空：$pkey"
  case "$pkey" in
    1.pattern) [ -z "$PAT1" ] || pattern_bad "重复条目 $pkey"; PAT1="$pval" ;;
    2.pattern) [ -z "$PAT2" ] || pattern_bad "重复条目 $pkey"; PAT2="$pval" ;;
    3.pattern) [ -z "$PAT3" ] || pattern_bad "重复条目 $pkey"; PAT3="$pval" ;;
    4.pattern) [ -z "$PAT4" ] || pattern_bad "重复条目 $pkey"; PAT4="$pval" ;;
    5.pattern) [ -z "$PAT5" ] || pattern_bad "重复条目 $pkey"; PAT5="$pval" ;;
    5.exclude) [ -z "$PAT5X" ] || pattern_bad "重复条目 $pkey"; PAT5X="$pval" ;;
    6.pattern) [ -z "$PAT6" ] || pattern_bad "重复条目 $pkey"; PAT6="$pval" ;;
    *) echo "GATE FAIL: 模式集含未知条目 $pkey —— fail-closed 停发"; exit 1 ;;
  esac
done < "$PATTERN_SRC"
if [ -z "$PAT1" ] || [ -z "$PAT2" ] || [ -z "$PAT3" ] || [ -z "$PAT4" ] || [ -z "$PAT5" ] || [ -z "$PAT5X" ] || [ -z "$PAT6" ]; then
  echo "GATE FAIL: 模式集不完整（六规则模式与规则 5 排除清单须齐全）—— fail-closed 停发"; exit 1
fi
if [ -n "${GATE_FP_KEY:-}" ] && ! command -v python3 >/dev/null 2>&1; then
  echo "GATE FAIL: 设了 GATE_FP_KEY（HMAC 指纹）但缺少 python3 —— fail-closed 停发"; exit 1
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
scan_error() { echo "GATE FAIL: $1 扫描过程出错（grep 退出码 $2）—— fail-closed 停发"; FAIL=1; printf '%s\terror\t\t\n' "$1" >> "$FINDINGS"; }
# tsv_esc <字符串>：把反斜杠/换行/制表符转义后输出，保证运行记录的 TSV 行不被文件名破坏。
tsv_esc() {
  local v="$1"
  v="${v//\\/\\\\}"; v="${v//$'\n'/\\n}"; v="${v//$'\t'/\\t}"
  printf '%s' "$v"
}
# 命中记录格式（collect 用 grep -Z 产生）：<路径> NUL <行号>:<内容> LF。路径以 NUL 为界、
# 行号取其后第一个冒号之前，内容里的 "ref:2:" 或路径里的 ":7:" 都不会造成错位。
# fp_hex：stdin -> 十六进制指纹。缺省 SHA-256；设 GATE_FP_KEY 时为 HMAC-SHA256。
# 输出指纹与 allowlist fp: 条目必须都经由本函数。
fp_hex() {
  if [ -n "${GATE_FP_KEY:-}" ]; then
    python3 -I -c 'import hashlib, hmac, os, sys; print(hmac.new(os.environ["GATE_FP_KEY"].encode("utf-8", "surrogateescape"), sys.stdin.buffer.read(), hashlib.sha256).hexdigest())'
  else
    sha256sum | cut -d' ' -f1
  fi
}
# record_hits <规则> <级别>：把 KEPT 中全部命中的位置（不含内容）记入 FINDINGS。
record_hits() {
  local path rest rel
  while IFS= read -r -d '' path || [ -n "$path" ]; do
    IFS= read -r rest || true
    rel="${path#"$DIR"/}"
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$(tsv_esc "$rel")" "${rest%%:*}" >> "$FINDINGS"
  done < "$KEPT"
}
# 0. 二进制文件：grep -I 会静默跳过，等于没扫。非空且无法按文本读取的文件一律 FAIL，
#    除非 allowlist 有与当前文件内容绑定的 bin:<相对路径>:<sha256> 条目。
#    （不可读文件由下方各规则的 grep 退出码 >=2 判 FAIL。）
: > "$WORK_TMP/binary"
while IFS= read -r -d '' f; do
  [ -r "$f" ] && [ -s "$f" ] || continue
  if ! grep -qI '' "$f"; then
    rel="${f#"$DIR"/}"
    sum="$(sha256sum "$f" | cut -d' ' -f1)"
    if ! grep -qxF "bin:$rel:$sum" "$EFF"; then
      echo "$rel: [二进制，无法按文本扫描 sha256=$sum]" >> "$WORK_TMP/binary"
      printf 'binary\tfail\t%s\t\n' "$(tsv_esc "$rel")" >> "$FINDINGS"
    fi
  fi
done < "$WORK_TMP/files"
# 0b. 符号链接：grep -r 不跟随、find -type f 也不计数——等于没扫；而发布时链接目标照样会被
#     带出去（可能指向目录外的任意文件）。一律 FAIL，换成实体文件后重跑即可被正常扫描。
if ! find "$DIR" -type l > "$WORK_TMP/links" 2>/dev/null; then
  echo "GATE FAIL: 枚举符号链接失败 —— fail-closed 停发"; exit 1
fi
if [ -s "$WORK_TMP/links" ]; then
  say_fail "存在符号链接（不会被扫描；请替换为实体文件后重跑）："
  head -5 "$WORK_TMP/links" | while IFS= read -r l; do echo "${l#"$DIR"/}"; done
  while IFS= read -r l; do printf 'symlink\tfail\t%s\t\n' "$(tsv_esc "${l#"$DIR"/}")" >> "$FINDINGS"; done < "$WORK_TMP/links"
fi
if [ -s "$WORK_TMP/binary" ]; then
  say_fail "存在无法按文本扫描的文件（人工复核后以 bin:<相对路径>:<sha256> 登记 allowlist）："
  head -5 "$WORK_TMP/binary"
fi

# collect: 运行一次 grep（-Z：路径后接 NUL，见 record_hits 注释），结果落 RAW；
# GRC 保存退出码（0=有命中 1=无命中 >=2=出错）。
collect() {
  grep -Z "$@" > "$RAW"
  GRC=$?
  return 0
}
# refilter: 以 grep -v 类过滤器对 RAW 再过滤（规则自带的内容排除，判定口径不变；-a：RAW 含 NUL）。
refilter() {
  grep -a "$@" "$RAW" > "$RAW2"
  GRC=$?
  if [ "$GRC" -ge 2 ]; then return 1; fi
  mv "$RAW2" "$RAW"
  return 0
}
# is_exempt <相对路径> <行号> <内容>：与生效条目精确比对（字面条目或 fp: 指纹条目）。
# fp: 条目与输出指纹同走 fp_hex（设了 GATE_FP_KEY 即 HMAC）；指纹最多算一次。
is_exempt() {
  local rel="$1" lineno="$2" content="$3" entry fp=""
  while IFS= read -r entry; do
    [ -z "$entry" ] && continue
    if [ "$entry" = "$rel:$lineno:$content" ]; then return 0; fi
    case "$entry" in
      fp:*)
        [ -n "$fp" ] || fp="$(printf '%s' "$rel:$lineno:$content" | fp_hex)"
        if [ -n "$fp" ] && [ "$entry" = "fp:$fp" ]; then return 0; fi
        ;;
    esac
  done < "$EFF"
  return 1
}
# apply_allowlist: RAW -> KEPT，仅剔除被精确条目豁免的命中。无法解析的记录一律保留（fail-closed）。
apply_allowlist() {
  : > "$KEPT"
  local path rest lineno content rel
  while IFS= read -r -d '' path || [ -n "$path" ]; do
    IFS= read -r rest || true
    lineno="${rest%%:*}"; content="${rest#*:}"
    rel="${path#"$DIR"/}"
    if [[ "$lineno" =~ ^[0-9]+$ ]] && is_exempt "$rel" "$lineno" "$content"; then continue; fi
    printf '%s\0%s\n' "$path" "$rest" >> "$KEPT"
  done < "$RAW"
}
# print_hits <模式 redact|assign|email>：打印 KEPT 前 5 条，默认脱敏。
print_hits() {
  local mode="$1" path rest lineno content len fp fline n=0
  while [ "$n" -lt 5 ] && { IFS= read -r -d '' path || [ -n "$path" ]; }; do
    IFS= read -r rest || true
    n=$((n + 1))
    if [ "${GATE_SHOW_CONTENT:-0}" = "1" ]; then printf '%s:%s\n' "$path" "$rest"; continue; fi
    lineno="${rest%%:*}"; content="${rest#*:}"
    case "$mode" in
      assign)
        printf '%s:%s:%s\n' "$path" "$lineno" "$(printf '%s' "$content" | sed -E -e 's#(://[^:/@ ]+:)[^@ ]+@#\1****@#g' -e "s/((password|passwd|pwd)[[:space:]]*[:=][[:space:]]*[\"']?)[^\"' ]+/\\1****/i")"
        ;;
      email)
        # 规则 6 用 grep -o，content 只是邮箱匹配本身，看不到前面的 scheme://用户:。凭据字符不得外泄：
        # 只要该行含 URL userinfo 口令（://用户:口令@），本行全部邮箱匹配整段掩码（不保留首字符；
        # 口令含邮箱字符集之外的字符时匹配可能从口令中段起，保留首字符同样泄露）。真实邮箱照旧保留首字符。
        fline="$(sed -n "${lineno}p" < "$path" 2>/dev/null)"
        if [[ "$fline" =~ ://[^[:space:]/@]*:[^[:space:]/@]*@ ]]; then
          printf '%s:%s:%s\n' "$path" "$lineno" "$(printf '%s' "$content" | sed -E 's/[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/****\1/g')"
        else
          printf '%s:%s:%s\n' "$path" "$lineno" "$(printf '%s' "$content" | sed -E 's/([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/\1****\2/g')"
        fi
        ;;
      *)
        len="$(printf '%s' "$content" | wc -c)"
        fp="$(printf '%s' "$content" | fp_hex)"
        printf '%s:%s: [内容已脱敏 len=%s fp=%s]\n' "$path" "$lineno" "$len" "$fp"
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
    record_hits rule1 fail
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
    record_hits rule2 fail
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
  record_hits rule3 fail
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
    record_hits rule4 fail
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
      record_hits rule5 warn
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
    record_hits rule6 warn
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
if [ "$WARN" -eq 1 ]; then echo "结果：WARN —— 须人工复核上述项后方可发布（exit 4，与 PASS 的 exit 0 不同）"; exit 4; fi
echo "结果：PASS"
