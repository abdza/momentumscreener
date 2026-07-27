#!/bin/bash
# One-session validation run: stream screener vs the TradingView candidate source.
# Started by cron at 16:00 MYT (= 04:00 ET) alongside pretop20.sh so both sources
# begin at the premarket open; exits on its own at 09:25 ET.
# Temporary - remove the cron entry once the comparison has been reviewed.

cd /home/abdza/momentumscreener
source venv/bin/activate
source secrets.env
python compare_stream_vs_pipeline.py --until 09:25 >> stream_comparison.log 2>&1
