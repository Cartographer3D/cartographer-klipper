#!/bin/bash

# Based upon the fantastic Beacon eddy current scanner support
# Copyright (C) 2020-2023 Matt Baker <baker.matt.j@gmail.com>
# Copyright (C) 2020-2023 Lasse Dalegaard <dalegaard@gmail.com>
# Copyright (C) 2023 Beacon <beacon3d.com>
# This file may be distributed under the terms of the GNU GPLv3 license.

KDIR="${HOME}/klipper"
KENV="${HOME}/klippy-env"

BKDIR="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

if [ ! -d "$KDIR" ] || [ ! -d "$KENV" ]; then
    echo "idm: klipper or klippy env doesn't exist"
    exit 1
fi

# install idm requirements to env
echo "Cartographer: installing python requirements to env, this may take 10+ minutes."
"${KENV}/bin/pip" install -r "${BKDIR}/requirements.txt"

# update link to idm.py
echo "Cartographer: linking modules into klipper"
for file in idm.py cartographer.py; do
    if [ -e "${KDIR}/klippy/extras/${file}" ]; then
        rm "${KDIR}/klippy/extras/${file}"
    fi
    ln -s "${BKDIR}/${file}" "${KDIR}/klippy/extras/${file}"
    if ! grep -q "klippy/extras/${file}" "${KDIR}/.git/info/exclude"; then
        echo "klippy/extras/${file}" >> "${KDIR}/.git/info/exclude"
    fi
done
echo "Cartographer Probe: installation successful."
