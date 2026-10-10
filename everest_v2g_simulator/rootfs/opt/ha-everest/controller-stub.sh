#!/bin/sh
# Replaces EVerest's admin-panel controller, which listens on all interfaces
# (port 8849). This App has no admin panel; the stub only lives while the
# EVerest manager (its parent) does.
while kill -0 "$PPID" 2>/dev/null; do sleep 2; done
