#!/bin/bash

set -eE
cd $(dirname $0)

TARGET="/tmp/backup-${HOSTNAME}-$(date +%F_%T).tar"
PW="topsecret"

echo "----- tarring -----"
time ./cycbackup.py -c cycbackup.yaml -t "${TARGET}"
ls -l "${TARGET}"
ls -lh "${TARGET}"
echo "----- encrypting -----"
time gpg -c --passphrase "${PW}" --batch --compress-algo bzip2 --bzip2-compress-level 9 "${TARGET}"
rm -v "${TARGET}"
ls -l "${TARGET}.gpg"
ls -lh "${TARGET}.gpg"
echo "----- all done -----"
