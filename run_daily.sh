#!/bin/bash
# Run this script once per day for 7 days.
# It advances the paper-forward run by one day.
#
# SETUP (run once):
#   chmod +x run_daily.sh
#
# DAILY USAGE:
#   ./run_daily.sh
#
# TO AUTOMATE (runs at 9:00 AM UTC daily):
#   crontab -e
#   Add this line:
#   0 9 * * * cd /Users/pythodevai/projects/claude-trader-bot && ./run_daily.sh >> logs/daily.log 2>&1

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "======================================"
echo " Claude Trader — Daily Run"
echo " $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "======================================"

mkdir -p logs

python3 scripts/run_paper_forward.py --config config/episode_01.yaml 2>&1 | tee -a logs/daily.log

echo ""
echo "Done. Check dashboard: streamlit run dashboard/app.py"
