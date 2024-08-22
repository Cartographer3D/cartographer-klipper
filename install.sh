#!/bin/bash

# Copyright (C) Cartographer3D 2023-2024

# Based upon the fantastic Beacon eddy current scanner support
# Copyright (C) 2020-2023 Matt Baker <baker.matt.j@gmail.com>
# Copyright (C) 2020-2023 Lasse Dalegaard <dalegaard@gmail.com>
# Copyright (C) 2023 Beacon <beacon3d.com>
# This file may be distributed under the terms of the GNU GPLv3 license.

KDIR="${HOME}/klipper"
KENV="${HOME}/klippy-env"
PYTHON_EXEC="$KENV/bin/python"

BKDIR="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

if [ ! -d "$KDIR" ] || [ ! -d "$KENV" ]; then
    echo "Cartographer: klipper or klippy env doesn't exist"
    exit 1
fi

# install Cartographer requirements to env
echo "Cartographer: installing python requirements to env, this may take 10+ minutes."
"${KENV}/bin/pip" install -r "${BKDIR}/requirements.txt"

# update link to scanner.py, cartographer.py & idm.py
echo "Cartographer: linking modules into klipper"
for file in idm.py cartographer.py scanner.py; do
    if [ -e "${KDIR}/klippy/extras/${file}" ]; then
        rm "${KDIR}/klippy/extras/${file}"
    fi
    ln -s "${BKDIR}/${file}" "${KDIR}/klippy/extras/${file}"
    if ! grep -q "klippy/extras/${file}" "${KDIR}/.git/info/exclude"; then
        echo "klippy/extras/${file}" >> "${KDIR}/.git/info/exclude"
    fi
done

python_version=$($PYTHON_EXEC -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
echo "Python version in Klippy environment: $python_version"

# Extract the major version number
major_version=$(echo $python_version | cut -d '.' -f1)

# Check if Python version is less than 3
if [ "$major_version" -lt 3 ]; then
    # Display upgrade message in red and require acknowledgment
    echo -e "\033[0;31mFor Cartographer to work, you will need to upgrade your Python environment to Python 3.\033[0m"
    read -p "Press enter to acknowledge..."
fi

echo "Cartographer Probe: installation successful."
