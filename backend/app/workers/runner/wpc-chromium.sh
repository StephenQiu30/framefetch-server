#!/bin/sh
set -eu
for browser in /opt/playwright/chromium-*/chrome-linux*/chrome; do
    if [ -x "$browser" ]; then
        exec "$browser" --no-sandbox --proxy-bypass-list='<-loopback>' "$@"
    fi
done
exit 127
