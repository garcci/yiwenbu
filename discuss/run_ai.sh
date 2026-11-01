#!/usr/bin/env bash
# 用法：
#   run_ai.sh agy   提示词文件 输出文件 [模型=gemini-3.8-flash-high]
#   run_ai.sh codex 提示词文件 输出文件 [模型=gpt-6-astra] [沙箱=read-only] [工作目录=临时目录]
# 后台跑命令，每15秒检查一次输出文件：非空且连续60秒不再变大就结束进程（防 agy 输出完不退出）。
# 总超时 agy 30分钟、codex 40分钟，到点强制结束并在输出文件末尾注明“超时”。
# 日志写到 输出文件.log。
set -u
tool=${1:?tool}; prompt=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); out=$3
mkdir -p "$(dirname "$out")"; out=$(cd "$(dirname "$out")" && pwd)/$(basename "$out"); log="$out.log"
: > "$out"

case "$tool" in
  agy)
    model=${4:-gemini-3.8-flash-high}; limit=1800
    work=$(mktemp -d)
    (cd "$work" && exec agy -p "$(cat "$prompt")" --model "$model" --sandbox --print-timeout 0s) > "$out" 2> "$log" &
    ;;
  codex)
    model=${4:-gpt-6-astra}; sandbox=${5:-read-only}; work=${6:-$(mktemp -d)}; limit=2400
    codex exec --skip-git-repo-check --ephemeral -C "$work" -s "$sandbox" -m "$model" \
      -c model_reasoning_effort='"ultra"' -o "$out" - < "$prompt" > "$log" 2>&1 &
    ;;
  *) echo "未知工具：$tool" >&2; exit 2 ;;
esac
pid=$!

size() { stat -f %z "$1" 2>/dev/null || echo 0; }
start=$(date +%s); last=-1; stable=0; status=done
while kill -0 "$pid" 2>/dev/null; do
  sleep 15
  now=$(date +%s); cur=$(size "$out")
  if [ "$cur" -gt 0 ] && [ "$cur" -eq "$last" ]; then stable=$((stable + 15)); else stable=0; fi
  last=$cur
  if [ "$stable" -ge 60 ]; then status=stalled; break; fi
  if [ $((now - start)) -ge "$limit" ]; then status=timeout; break; fi
done

if kill -0 "$pid" 2>/dev/null; then
  pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null
fi
wait "$pid" 2>/dev/null; rc=$?
[ "$status" = timeout ] && printf '\n\n（超时：%s 秒内未完成，已强制结束）\n' "$limit" >> "$out"
echo "run_ai: tool=$tool model=$model status=$status rc=$rc elapsed=$(( $(date +%s) - start ))s bytes=$(size "$out")" | tee -a "$log"
