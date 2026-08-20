#!/bin/sh
set -eu

export WEB_HOST=127.0.0.1
export WEB_PORT="${WEB_PORT:-8080}"

if [ -x ./env/bin/python ]; then
    exec ./env/bin/python main.py -vv
fi

exec python3 main.py -vv
