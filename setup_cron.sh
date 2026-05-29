#!/bin/bash
# Adds a daily cron job to run the paper-forward trader at 09:00 UTC every day.
# Run this ONCE to set it up. It will not add duplicates.

PYTHON="/Users/pythodevai/projects/claude-trader-bot/venv/bin/python3"
PROJECT="/Users/pythodevai/projects/claude-trader-bot"
SCRIPT="scripts/run_paper_forward.py"
CONFIG="config/episode_01.yaml"
LOG="$PROJECT/logs/daily.log"

CRON_LINE="0 9 * * * cd $PROJECT && $PYTHON $SCRIPT --config $CONFIG >> $LOG 2>&1"

mkdir -p "$PROJECT/logs"

# check if already exists
if crontab -l 2>/dev/null | grep -q "run_paper_forward"; then
    echo "Cron job already exists:"
    crontab -l | grep "run_paper_forward"
else
    # add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "Cron job added successfully."
    echo ""
    echo "It will run every day at 09:00 UTC."
    echo "Logs will be saved to: $LOG"
    echo ""
    echo "To verify:"
    echo "  crontab -l"
    echo ""
    echo "To remove it later:"
    echo "  crontab -e  (delete the run_paper_forward line)"
fi
