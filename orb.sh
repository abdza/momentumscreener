#!/bin/bash

cd /home/abdza/momentumscreener
source venv/bin/activate
source secrets.env
python orb_screener.py --bot-token "$TELEGRAM_BOT_TOKEN" --chat-id "$TELEGRAM_CHAT_ID"
