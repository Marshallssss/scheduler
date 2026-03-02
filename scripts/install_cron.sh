#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'HELP'
安装 Scheduler 的生产 cron 任务（幂等覆盖受管块）。

用法:
  scripts/install_cron.sh --config /absolute/path/.scheduler.toml [--log-dir /path/to/logs] [--cron-tz Asia/Shanghai] [--dry-run]

参数:
  --config   Scheduler 配置文件绝对路径（必填）
  --log-dir  cron 日志目录，默认 ~/.project_scheduler/logs
  --cron-tz  crontab 任务时区，默认 Asia/Shanghai
  --dry-run  只输出将要安装的完整 crontab，不写入系统
  -h, --help 显示帮助
HELP
}

CONFIG_PATH=""
LOG_DIR="$HOME/.project_scheduler/logs"
CRON_TZ_VALUE="Asia/Shanghai"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_PATH="${2:-}"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="${2:-}"
      shift 2
      ;;
    --cron-tz)
      CRON_TZ_VALUE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      show_help
      exit 1
      ;;
  esac
done

if [[ -z "$CONFIG_PATH" ]]; then
  echo "缺少必填参数 --config" >&2
  show_help
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "配置文件不存在: $CONFIG_PATH" >&2
  exit 1
fi

SCHEDULER_BIN="$(command -v scheduler || true)"
if [[ -z "$SCHEDULER_BIN" ]]; then
  echo "未找到 scheduler 命令，请先安装: pip install -e .[dev]" >&2
  exit 1
fi

CONFIG_PATH="$(cd "$(dirname "$CONFIG_PATH")" && pwd)/$(basename "$CONFIG_PATH")"
SCHEDULER_BIN="$(cd "$(dirname "$SCHEDULER_BIN")" && pwd)/$(basename "$SCHEDULER_BIN")"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron.log"

escape_for_cron() {
  printf '%s' "$1" | sed 's/ /\\ /g'
}

CONFIG_ESC="$(escape_for_cron "$CONFIG_PATH")"
SCHEDULER_ESC="$(escape_for_cron "$SCHEDULER_BIN")"
LOG_ESC="$(escape_for_cron "$LOG_FILE")"

BEGIN_MARK="# >>> scheduler managed jobs >>>"
END_MARK="# <<< scheduler managed jobs <<<"

tmp_existing="$(mktemp)"
tmp_cleaned="$(mktemp)"
tmp_block="$(mktemp)"
tmp_final="$(mktemp)"

cleanup() {
  rm -f "$tmp_existing" "$tmp_cleaned" "$tmp_block" "$tmp_final"
}
trap cleanup EXIT

crontab -l > "$tmp_existing" 2>/dev/null || true

backup_dir="$HOME/.project_scheduler/cron_backups"
mkdir -p "$backup_dir"
backup_file="$backup_dir/crontab_$(date +%Y%m%d_%H%M%S).bak"
cp "$tmp_existing" "$backup_file"

awk -v begin="$BEGIN_MARK" -v end="$END_MARK" '
  $0 == begin {in_block = 1; next}
  $0 == end {in_block = 0; next}
  !in_block {print}
' "$tmp_existing" > "$tmp_cleaned"

cat > "$tmp_block" <<BLOCK
$BEGIN_MARK
CRON_TZ=$CRON_TZ_VALUE
0 9 * * * $SCHEDULER_ESC --config $CONFIG_ESC jobs run-daily --step reminders >> $LOG_ESC 2>&1
45 17 * * * $SCHEDULER_ESC --config $CONFIG_ESC jobs run-daily --step progress-nudge >> $LOG_ESC 2>&1
55 17 * * * $SCHEDULER_ESC --config $CONFIG_ESC report generate --period daily >> $LOG_ESC 2>&1
0 18 * * 5 $SCHEDULER_ESC --config $CONFIG_ESC jobs run-weekly >> $LOG_ESC 2>&1
10 18 28-31 * * $SCHEDULER_ESC --config $CONFIG_ESC jobs run-monthly >> $LOG_ESC 2>&1
$END_MARK
BLOCK

if [[ -s "$tmp_cleaned" ]]; then
  cat "$tmp_cleaned" > "$tmp_final"
  printf '\n' >> "$tmp_final"
fi
cat "$tmp_block" >> "$tmp_final"

if [[ "$DRY_RUN" -eq 1 ]]; then
  cat "$tmp_final"
  echo
  echo "[dry-run] 未写入系统 crontab"
  echo "[dry-run] 已备份当前 crontab: $backup_file"
  exit 0
fi

crontab "$tmp_final"

echo "已安装 scheduler cron 任务"
echo "配置文件: $CONFIG_PATH"
echo "日志文件: $LOG_FILE"
echo "已备份原 crontab: $backup_file"
