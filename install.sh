#!/bin/bash

KDIR="${HOME}/klipper"
KENV="${HOME}/klippy-env"

BKDIR="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

if [ ! -d "$KDIR" ] || [ ! -d "$KENV" ]; then
    echo "idm: klipper or klippy env doesn't exist"
    exit 1
fi

# install idm requirements to env
echo "idm: installing python requirements to env, this may take 10+ minutes."
"${KENV}/bin/pip" install -r "${BKDIR}/requirements.txt"

# update link to idm.py
echo "idm: linking klippy to idm.py."
if [ -e "${KDIR}/klippy/extras/idm.py" ]; then
    rm "${KDIR}/klippy/extras/idm.py"
fi
if [ -e "${KDIR}/klippy/extras/idm_accel.py" ]; then
    rm "${KDIR}/klippy/extras/idm_accel.py"
fi
ln -s "${BKDIR}/idm.py" "${KDIR}/klippy/extras/idm.py"
ln -s "${BKDIR}/idm_accel.py" "${KDIR}/klippy/extras/idm_accel.py"
# exclude idm.py from klipper git tracking
if ! grep -q "klippy/extras/idm.py" "${KDIR}/.git/info/exclude"; then
    echo "klippy/extras/idm.py" >> "${KDIR}/.git/info/exclude"
fi
if ! grep -q "klippy/extras/idm_accel.py" "${KDIR}/.git/info/exclude"; then
    echo "klippy/extras/idm_accel.py" >> "${KDIR}/.git/info/exclude"
fi
echo "idm: installation successful."
