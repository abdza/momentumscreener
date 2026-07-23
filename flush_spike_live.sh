#!/bin/bash

cd /home/abdza/momentumscreener
source venv/bin/activate
source secrets.env
python flush_spike_live_trader.py
