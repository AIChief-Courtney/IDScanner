#!/bin/bash
exec python3 app.py &
sleep 10
exec python3 demo.py
