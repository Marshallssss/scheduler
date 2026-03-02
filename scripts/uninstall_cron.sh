#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'HELP'
卸载 Scheduler 的受管 cron 任务（仅移除受管块，不影响其他任务）。

用法:
  scripts/uninstall_cron.sh [--dry-run]

参数:
  --dry-run  只输出卸载后的 crontab，不写入系统
  -h, --help 显示帮助
HELP
}

DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
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

BEGIN_MARK="# >>> scheduler managed jobs >>>"
END_MARK="# <<< scheduler managed jobs <<<"

tmp_existing="$(mktemp)"
tmp_cleaned="$(mktemp)"

cleanup() {
  rm -f "$tmp_existing" "$tmp_cleaned"
}
trap cleanup EXIT

crontab -l > "$tmp_existing" 2>/dev/null || true

if ! grep -qF "$BEGIN_MARK" "$tmp_existing"; then
  echo "未检测到 scheduler 受管 cron 块，无需卸载"
  exit 0
fi

backup_dir="$HOME/.project_scheduler/cron_backups"
mkdir -p "$backup_dir"
backup_file="$backup_dir/crontab_$(date +%Y%m%d_%H%M%S).bak"
cp "$tmp_existing" "$backup_file"

awk -v begin="$BEGIN_MARK" -v end="$END_MARK" '
  $0 == begin {in_block = 1; next}
  $0 == end {in_block = 0; next}
  !in_block {print}
' "$tmp_existing" > "$tmp_cleaned"

if [[ "$DRY_RUN" -eq 1 ]]; then
  cat "$tmp_cleaned"
  echo
  echo "[dry-run] 未写入系统 crontab"
  echo "[dry-run] 已备份当前 crontab: $backup_file"
  exit 0
fi

if [[ -s "$tmp_cleaned" ]]; then
  crontab "$tmp_cleaned"
else
  crontab -r
fi

echo "已卸载 scheduler 受管 cron 块"
echo "已备份原 crontab: $backup_file"
