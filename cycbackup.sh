#!/bin/bash

set -eE
cd $(dirname $0)

TARGET="/tmp/backup-${HOSTNAME}-$(date +%F_%T).tar"
PW="topsecret"

./cycbackup.py -c config.yaml -t "${TARGET}"
gpg -c --passphrase "${PW}" --batch "${TARGET}"
rm "${TARGET}"
xz "${TARGET}.gpg"
ls -lh "${TARGET}.gpg.xz"
