#!/bin/bash

if [[ -n "$PROXY_HOST" && -n "$PROXY_PORT" ]]; then
    # resolve to ip now, if possible
    if IP=$(host "$PROXY_HOST" | head -n 1 | cut -d ' ' -f 4); then
        export PROXY_HOST=$IP
        echo "IP: $IP"
    fi

    # if PROXY_CA_FILE is set and does not exist..
    if [[ -n "$PROXY_CA_FILE" ]] && [ ! -f "$PROXY_CA_FILE" ]; then
        if [[ -n "$PROXY_CA_URL" ]]; then
            # Get CA via specified URL
            until curl --output /dev/null --silent --head --fail "$PROXY_HOST:$PROXY_PORT"; do
                printf 'Waiting for proxy...'
                sleep 1
            done

            curl -x "$PROXY_HOST:$PROXY_PORT"  "$PROXY_CA_URL" > "$PROXY_CA_FILE"
        fi
    fi

    export http_proxy=http://$PROXY_HOST:$PROXY_PORT
    export https_proxy=http://$PROXY_HOST:$PROXY_PORT
fi

# Run browser here
eval "$@"

