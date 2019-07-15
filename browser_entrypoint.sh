#!/bin/bash

if [[ -n "$PROXY_HOST" && -n "$PROXY_PORT" ]]; then
    # resolve to ip now, if possible
    if IP=$(host "$PROXY_HOST" | head -n 1 | cut -d ' ' -f 4); then
        export PROXY_HOST=$IP
        echo "IP: $IP"
    fi

    export http_proxy=http://$PROXY_HOST:$PROXY_PORT
    export https_proxy=http://$PROXY_HOST:$PROXY_PORT

    # if PROXY_CA_FILE is set and does not exist..
    if [[ -n "$PROXY_CA_FILE" ]] && [ ! -f "$PROXY_CA_FILE" ]; then
        if [[ -n "$PROXY_CA_URL" ]]; then
            # Get CA via specified URL
            until wget -O "$PROXY_CA_FILE" "$PROXY_CA_URL"; do
                printf 'Waiting for proxy...'
                sleep 1
            done
        fi
    fi
fi

# Run browser here
eval "$@"

