#!/bin/sh
# Build the spotifytap helper into <repo>/bin/spotifytap
set -eu
cd "$(dirname "$0")/spotifytap"
mkdir -p ../../bin
swiftc -O main.swift -o ../../bin/spotifytap \
    -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
echo "built bin/spotifytap"
