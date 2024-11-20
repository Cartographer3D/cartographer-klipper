#!/bin/bash

while getopts s:t:f:b: flag
do
    case "${flag}" in
        s) switch=${OPTARG};;
		t) ftype=${OPTARG};;
		f) flash=${OPTARG};;
		b) beta=${OPTARG};;
    esac
done
# Define repository URLs
CARTOGRAPHER_KLIPPER_REPO="https://github.com/Cartographer3D/cartographer-klipper.git"
KATAPULT_REPO="https://github.com/Arksine/katapult.git"

if [[ $beta == "beta" ]]; then
	TARBALL_URL="https://api.github.com/repos/Cartographer3D/cartographer-klipper/tarball/master"
else
	TARBALL_URL="https://api.github.com/repos/Cartographer3D/cartographer-klipper/tarball/beta-firmware"
fi
TEMP_DIR="/tmp/cartographer-klipper"

KATAPULT_DIR="$HOME/katapult"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[1;36m'
NC='\033[0m' # No Color
### Written by KrauTech (https://github.com/krautech)

### Written for Cartographer3D

### Credit to Esoterical (https://github.com/Esoterical)
### I used inspiration and snippet from his debugging script
### Thanks

if systemctl is-active --quiet "klipper.service" ; then
	result=$(curl 127.0.0.1:7125/printer/objects/query?print_stats)
	if grep -q "'state': 'printing'" <<< $result; then
		echo "Printer is NOT IDLE. Please stop or finish whatever youre doing before running this script."
		exit;
	else
		if grep -q "'state': 'paused'" <<< $result; then
			echo "Printer is NOT IDLE. Please stop or finish whatever youre doing before running this script."
			exit;
		fi
	fi
else
	sudo service klipper stop
fi
##
# Color  Variables
##
red='\r\033[31m'
green='\r\033[32m'
blue='\r\033[1;36m'
yellow='\r\033[1;33m'
clear='\e[0m'
##
# Color Functions
##
ColorRed(){
	echo -ne $red$1$clear
}
ColorGreen(){
	echo -ne $green$1$clear
}
ColorBlue(){
	echo -ne $blue$1$clear
}
ColorYellow(){
	echo -ne $yellow$1$clear
}
header(){
clear
printf "${BLUE}
   ____                  _                                            _                   
  / ___|   __ _   _ __  | |_    ___     __ _   _ __    __ _   _ __   | |__     ___   _ __ 
 | |      / _  | | '__| | __|  / _ \   / _  | | '__|  / _  | | '_ \  | '_ \   / _ \ | '__|
 | |___  | (_| | | |    | |_  | (_) | | (_| | | |    | (_| | | |_) | | | | | |  __/ | |   
  \____|  \__,_| |_|     \__|  \___/   \__, | |_|     \__,_| | .__/  |_| |_|  \___| |_|   
                                       |___/                 |_|                          
${NC}"
printf "${RED}Firmware Script ${NC} v1.1.1\n"
printf "Created by ${GREEN}KrauTech${NC} ${BLUE}(https://github.com/krautech)${NC}\n"
echo
echo
printf "${RED}###################################################################################${NC}\n"
#echo $switch
#echo $ftype
}
header;
saved_uuid=""
queryID=""

disclaimer() {
	# Show Disclaimer FUNCTION
	echo "******************************************************************"
	echo "* Attention *"
	echo "******************************************************************"
	echo
	echo "This script is designed to update your firmware via Katapult/DFU/USB"
	echo ""
	printf "${RED}USE AT YOUR OWN RISK${NC}"
	echo ""
	echo "This script is available for review at: "
	printf "${BLUE}https://github.com/krautech/scripts/blob/main/cartographer/scripts/release/firmware.sh${NC}\n\n"
	echo

	while true; do
		read -p "Do you wish to run this program? (yes/no) " yn < /dev/tty
		case $yn in
			[Yy]* ) break;;
			[Nn]* ) exit;;
			* ) echo "Please answer yes or no.";;
		esac
	done
}

menu(){
	# Show the Main Menu FUNCTION
	header;
	if [[ $findUUID != "" ]] && ([[ $flash == "can" ]] || [[ $flash == "" ]]); then
		echo -ne "$(ColorBlue 'Cartographer Canbus UUID detected in klippy.log: ')"
		echo $findUUID
		echo 
	fi
	if [[ $queryID != "" ]] && ([[ $flash == "can" ]] || [[ $flash == "" ]]); then
		echo -ne "$(ColorBlue 'Cartographer Canbus UUID detected in via lookup: ')"
		echo $queryID
		echo 
	fi
	if [[ $canbootID != "" ]] || [[ $katapultID != "" ]]; then
		echo -ne "$(ColorGreen 'Canbus Katapult Device Found for Flashing: ')Klippy.log UUID $canbootID $katapultID\n"
	fi
	if [[ $queryID != "" ]]; then
		echo -ne "$(ColorGreen 'Canbus Katapult Device Found for Flashing: ')Lookup UUID ${queryID}\n"
	fi
	if [[ $dfuID != "" ]]; then
		echo -ne "$(ColorGreen 'DFU Device Found for Flashing')\n"
	fi
	if [[ $usbID != "" ]]; then
		echo -ne "$(ColorGreen 'USB Katapult Device Found for Flashing')\n"
	fi
	if [[ $canbootID == "" ]] && [[ $katapultID == "" ]] && [[ $dfuID == "" ]] && [[ $usbID == "" ]] && [[ $queryID == "" ]]; then
		echo -ne "$(ColorRed 'No Device Found in Flashing Mode')\n"
	fi
	if [ ! -d ~/katapult ] || [ ! -d $CARTOGRAPHER_KLIPPER_DIR ]; then
	echo -ne ""
	else
		if [[ $flash == "dfu" ]] || [[ $flash == "" ]]; then
			echo -ne "
					$(ColorGreen '2)') Run lsusb"
			echo
		fi
			echo -ne "
					$(ColorGreen '3)') Check For Flashable Devices"
		canCheck=$(ip -s -d link | grep "can0")
		if [[ $canCheck != "" ]] && ([[ $flash == "can" ]] || [[ $flash == "" ]]); then
			echo -ne "
					$(ColorGreen '4)') Check Canbus UUID And Or Enter CANBUS Katapult Mode\n"
			echo -ne "
					$(ColorGreen '5)') Lookup CANBUS UUID's"
		fi
		echo
		if [[ $canbootID != "" ]] || [[ $katapultID != "" ]] && ([[ $flash == "can" ]] || [[ $flash == "" ]]); then
			if [[ $canbootID != "" ]]; then
				uuid=$canbootID
			fi
			if [[ $katapultID != "" ]]; then
				uuid=$katapultID
			fi
			echo -ne "
				$(ColorBlue '6)') Flash Firmware via Katapult CAN (Device: $uuid)"
		fi
		if [[ $queryID == *"Klipper"* ]]; then
		  queryID=""
		fi
		if [[ $queryID != "" ]] && ([[ $flash == "can" ]] || [[ $flash == "" ]]); then
			echo -ne "
				$(ColorBlue '7)') Flash Firmware via Katapult CAN (Device: $queryID)"
		fi
		if [[ $dfuID != "" ]] && ([[ $flash == "dfu" ]] || [[ $flash == "" ]]); then
			echo -ne "
				$(ColorBlue '8)') Flash Firmware via DFU"
		fi
		if [[ $usbID != "" ]] && ([[ $flash == "usb" ]] || [[ $flash == "" ]]); then
			echo -ne "
				$(ColorBlue '9)') Flash Firmware via Katapult USB"
		fi
	fi
	echo
	echo
	echo -ne "\n	
		$(ColorRed 'r)') Reboot
		$(ColorRed 'q)') Exit without Rebooting\n"
	echo -ne "\n	
		$(ColorBlue 'Choose an option:') "
    read a
	COLUMNS=12
    case $a in
	    1) menu ;;
		2) check_lsusb ;;
	    3) initialChecks ; menu ;;
	    4) checkUUID ; menu ;;
		5) uuidLookup ; menu ;;
		6) whichFlavor 1 $uuid; menu ;;
		7) whichFlavor 1 $queryID; menu ;;
		8) whichFlavor 2 $dfuID; menu ;;
		9) whichFlavor 3 $usbID; menu ;;
		"lsusb") 
		lsusb
		read -p "Press enter to return to main menu"; menu ;;
		"q") sudo service klipper start; delete_temp;;
		"r") sudo reboot; delete_temp;;
		*) echo -e $red"Wrong option."$clear;;
    esac
}
# Function to handle key press
stop_loop() {
    echo "Stopping the loop."
	trap - SIGINT  # Reset the trap
    menu
}

check_lsusb(){
# Trap any key press to stop the loop
	trap stop_loop SIGINT

	while true; do
		if lsusb | grep -q "DFU Mode"; then
			dfuID=$(lsusb | grep "DFU Mode" | awk '{print $6}');
			found=1
			read -p "DFU device found! Press any key to return to main menu."
			menu  # Exit the loop if a DFU device is found
		else
			echo "DFU device not found, checking again... Press any key to return to main menu."
		fi

		# Check for a key press with a timeout of 2 seconds
		read -t 1 -n 1 key
		if [[ $? -eq 0 ]]; then
			stop_loop
		fi
	done
}
initialChecks(){
	# Begin Checking For Devices FUNCTION
	header;
	echo "Running Checks for Cartographer Devices in Katapult Mode (Canbus & USB) or DFU"
	echo
	echo "This can take a few moments.. please wait."
	echo 
	installPre
	
	if [[ ! -d "$TEMP_DIR" ]]; then
		# Create /tmp directory if not exists
		mkdir -p "$TEMP_DIR"
		curl -L "$TARBALL_URL" | tar -xz -C "$TEMP_DIR"
	fi
	# Find the extracted folder name (GitHub includes commit hash in the folder name)
	CARTOGRAPHER_KLIPPER_DIR=$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d)
	
	
	# Check for Device in DFU Mode Instead
	if [[ $flash == "dfu" ]] || [[ $flash == "" ]]; then
		dfuCheck=$(lsusb | grep -oP "DFU Mode")
		if [[ $dfuCheck == "DFU Mode" ]]; then
			# Save DFU Device ID
			dfuID=$(lsusb | grep "DFU Mode" | awk '{print $6}');
			found=1
			#echo "DFU Flash is Disabled
		fi
	fi
	if [[ $flash == "usb" ]] || [[ $flash == "" ]]; then
		# Check For Katapult USB Serials
		if [[ -d /dev/serial/by-id/ ]]; then
			# Check for Cartographer USB
			usbCartoCheck=$(ls -l /dev/serial/by-id/ | grep -oP "Cartographer")
			usbKatapultCheck=$(ls -l /dev/serial/by-id/ | grep -oP "katapult")
			sleep 5
			if [[ $usbCartoCheck == "Cartographer" ]]; then
				# Save USB ID
				cartoID=$(ls -l /dev/serial/by-id/ | grep "Cartographer" | awk '{print $9}');
				cd ~/klipper/scripts
				~/klippy-env/bin/python -c "import flash_usb as u; u.enter_bootloader('/dev/serial/by-id/${cartoID}')"
				sleep 5
				usbID=$(ls -l /dev/serial/by-id/ | grep "katapult" | awk '{print $9}');
				found=1
			fi
			if [[ $usbKatapultCheck == "katapult" ]]; then
				usbID=$(ls -l /dev/serial/by-id/ | grep "katapult" | awk '{print $9}');
				found=1
			fi
		fi
	fi
	if [[ $flash == "can" ]] || [[ $flash == "" ]]; then
		# check for Katapult CAN Devices
		if [ -d ~/katapult ]; then
			cd ~/katapult
			git pull > /dev/null 2>&1
			canCheck=$(ip -s -d link | grep "can0")
			if [[ $canCheck != "" ]]; then
				findUUID=$(grep -E "\[scanner\]" ~/printer_data/logs/klippy.log -A 3 | grep uuid | tail -1 | awk '{print $3}')
				if [[ $findUUID == "" ]]; then
					findUUID=$(grep -E "\[cartographer\]" ~/printer_data/logs/klippy.log -A 3| grep uuid | tail -1 | awk '{print $3}')
					if [[ $findUUID != "" ]]; then
						checkuuid=$(python3 ~/katapult/scripts/flashtool.py -i can0 -u $findUUID -r | grep -s "Flash Success")
						sleep 5
						fi 
				else
					checkuuid=$(python3 ~/katapult/scripts/flashtool.py -i can0 -u $findUUID -r | grep -s "Flash Success")
					sleep 5
				fi
				# Check for canboot device
				canbootCheck=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -v 'Klipper$' | grep -v 'Total.*uuids found' | grep 'CanBoot')
				if [[ $canbootCheck != "" ]]; then
					# Save CanBoot Device UUID
					canbootID=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -v 'Klipper$' | grep -v 'Total.*uuids found' | grep 'CanBoot' | awk -F'canbus_uuid=' '{print $2}' | awk -F', ' '{print $1}'
	)
					found=1
				fi	
				# Check for Canbus Katapult device
				katapultCheck=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -v 'Klipper$' | grep -v 'Total.*uuids found' | grep 'Katapult')
				if [[ $katapultCheck != "" ]]; then
					# Save Katapult Device UUID
					katapultID=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -v 'Klipper$' | grep -v 'Total.*uuids found' | grep 'Katapult' | awk -F'canbus_uuid=' '{print $2}' | awk -F', ' '{print $1}'
	)
					found=1
				fi
			fi
		fi
	fi
}

installPre(){
	# Installs all needed files FUNCTION
	check_git_installed
	check_dfu_util_installed
	check_katapult
}
# Function to check if Git is installed
check_git_installed() {
    if command -v git >/dev/null 2>&1; then
        echo "Git is already installed. Proceeding..."
    else
        echo "Git is not installed. Installing Git..."
        install_git
    fi
}
# Function to check if dfu-util is installed
check_dfu_util_installed() {
    if command -v dfu-util >/dev/null 2>&1; then
        echo "dfu-util is already installed. Proceeding..."
    else
        echo "dfu-util is not installed. Installing dfu-util..."
        install_dfu_util
    fi
}
# Function to check if a git repository is already pulled
check_repo_pulled() {
    local repo_dir=$1
    local repo_url=$2

    if [ -d "$repo_dir/.git" ]; then
        echo "Repository already exists at $repo_dir. Proceeding..."
    else
        echo "Repository not found at $repo_dir. Pulling from $repo_url..."
        git clone "$repo_url" "$repo_dir"
        if [ $? -eq 0 ]; then
            echo "Repository cloned successfully."
        else
            echo "Failed to clone the repository. Please check your internet connection or repo URL."
            exit 1
        fi
    fi
}

# Check if katapult is pulled
check_katapult() {
    check_repo_pulled "$KATAPULT_DIR" "$KATAPULT_REPO"
}
# Function to install Git
install_git() {
    if [ -x "$(command -v apt)" ]; then
        sudo apt update
        sudo apt install git -y
    elif [ -x "$(command -v yum)" ]; then
        sudo yum install git -y
    elif [ -x "$(command -v dnf)" ]; then
        sudo dnf install git -y
    elif [ -x "$(command -v pacman)" ]; then
        sudo pacman -S git --noconfirm
    else
        echo "Package manager not supported. Please install Git manually."
        exit 1
    fi
    echo "Git installed successfully."
}
# Function to install dfu-util
install_dfu_util() {
    if [ -x "$(command -v apt)" ]; then
        sudo apt update
        sudo apt install dfu-util -y
    elif [ -x "$(command -v yum)" ]; then
        sudo yum install dfu-util -y
    elif [ -x "$(command -v dnf)" ]; then
        sudo dnf install dfu-util -y
    elif [ -x "$(command -v pacman)" ]; then
        sudo pacman -S dfu-util --noconfirm
    else
        echo "Package manager not supported. Please install dfu-util manually."
        exit 1
    fi
    echo "dfu-util installed successfully."
}
uuidLookup(){
	header;
	canCheck=$(ip -s -d link | grep "can0")
	if [[ $canCheck != "" ]]; then 
		python3 ~/katapult/scripts/flashtool.py -q | grep -v 'Klipper$'
	else
		echo "CANBUS is not configured on this host"
	fi
	read -p "Press enter to go back"
	
}
checkUUID(){
	# Checks Users UUID and Put Device into Katapult Mode
	header;
	canCheck=$(ip -s -d link | grep "can0")
	if [[ $canCheck != "" ]]; then 
		echo "This is only needed if youre using CANBUS"
		echo 
		echo "Please enter your cartographer UUID"
		echo "found usually in your printer.cfg under [cartographer] or [scanner]"
		echo 
		echo "To go back: b"
		echo
		echo -n "UUID: "
		read -p "" -e uuid
		
		# If user entered a valid UUID
		if ! [[ $uuid == "b" ]]; then
			cd ~/katapult
			git pull > /dev/null 2>&1
			# Check If UUID is valid and puts device into Katapult Mode
			check2uuid=$(python3 ~/katapult/scripts/flashtool.py -i can0 -u $uuid -r | grep -s "Flash Success")
			sleep 5
			if [[ $check2uuid == "Flash Success" ]]; then
				# Check for canboot device
				canboot2Check=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -m 1 "CanBoot")
				sleep 5
				if [[ $canboot2Check != "" ]]; then
					# Save CanBoot Device UUID
					canboot2ID=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -m 1 -oP "canbus_uuid=\K.*" | sed -e 's/, Application: CanBoot//g')
					found=1
					findqueryUUID=$uuid
					queryID=$canboot2ID
					if [[ $queryID == *"Klipper"* ]]; then
					  queryID=""
					fi
				fi	
				# Check for Canbus Katapult device
				katapult2Check=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -m 1 "Katapult")
				sleep 5
				if [[ $katapult2Check != "" ]]; then
					# Save Katapult Device UUID
					katapult2ID=$(~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0 | grep -m 1 -oP "canbus_uuid=\K.*" | sed -e 's/, Application: Katapult//g')
					found=1
					findqueryUUID=$uuid
					queryID=$katapult2ID
					if [[ $queryID == *"Klipper"* ]]; then
					  queryID=""
					fi
				fi
				if [[ $found == 1 ]]; then
					printf "${uuid} UUID Check: ${GREEN}Success & Entered Katapult Mode${NC}\n"
					read -p "Press enter to check for flashable device"
					uuid=""
					initialChecks;
					##echo "DEBUG CHECK UUID:"$checkuuid
				else
					echo "UUID Check Failed: Device not found."
					read -p "Press enter to go back"
					uuid=""
				fi
			else
				echo "UUID Check Failed, Device couldnt enter Katapult mode."
				read -p "Press enter to go back"
				uuid=""
			fi
		fi
	else
		echo "CANBUS is not configured on this host device."
		read -p "Press enter to go back"
	fi
}
whichFlavor(){
	if [[ $ftype == "katapult" ]]; then
		flashFirmware 2 $1
	else
		flashFirmware 1 $1
		# # Tap vs non tap
		# header;
		# echo "Unsure what to do? Ask us on discord (https://discord.gg/yzazQMEGS2)"
		# echo
		# echo -ne "\n	
			# $(ColorGreen '1)') 5.0.0"
		# echo -ne "\n
			# $(ColorRed '6)') Back"
		# echo -ne "\n	
			# $(ColorBlue 'Choose an option:') "
		# read a
		# COLUMNS=12
		# case $a in
			# 1) flashFirmware 1 $1; menu ;;
			# 2) flashFirmware 2 $1; menu ;;
			# 6) menu ;;
			# *) echo -e $red"Wrong option."$clear;;
		# esac
	fi
}
###########################
# Helper function to sort firmware files
sort_firmware_files() {
    awk '
    BEGIN { 
        order["1m"]=1; 
        order["500k"]=2; 
        order["250k"]=3; 
        order["usb"]=4; 
    }
    {
        for (key in order) {
            if (index($0, key)) {
                print order[key] ":" $0;
                next;
            }
        }
        print 5 ":" $0;
    }
    ' | sort -t: -k1,1n | cut -d: -f2
}

flashFirmware(){
	# List Firmware for Found Device FUNCTION
	header;
	options=()
	echo "Pick which firmware you want to install, if unsure ask on discord (https://discord.gg/yzazQMEGS2)"
	echo
	# Check if canbootID or katapultID are set
	if [[ -n $canbootID || -n $katapultID ]] && [[ $2 == 1 ]]; then
		# Retrieve CANBus bitrate
		bitrate=$(ip -s -d link show can0 | grep -oP 'bitrate\s\K\w+')
		printf "Your Host CANBus is configured at ${RED}Bitrate: $bitrate${NC}\n"
		printf "${BLUE}Flashing ${canbootID}${katapultID} via ${GREEN}CANBUS - KATAPULT${NC}\n\n"

		# Update repository
		cd "$CARTOGRAPHER_KLIPPER_DIR" || exit

		# Determine flashing type
		if [[ $ftype == "katapult" ]]; then
			cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/katapult-deployer/" || exit

			# Set search parameters based on switch
			if [[ $switch == "canbus" ]]; then
				exclude_pattern="*usb*"
			elif [[ $switch == "usb" ]]; then
				include_pattern="*usb*"
			else
				include_pattern="*"
			fi

			# Find and sort firmware files
			mapfile -t options < <(
				find . -maxdepth 1 -type f ! -name "*.txt" \( \
					${include_pattern:+-name "$include_pattern"} \
					${exclude_pattern:+! -name "$exclude_pattern"} \
				\) -printf "%f\n" | sort_firmware_files
			)

		else
			# Set directory based on parameter
			if [[ $1 == 1 ]]; then
				cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/survey" || exit
			else
				cd "$CARTOGRAPHER_KLIPPER_DIR/cartographer-klipper/firmware/v2-v3/" || exit
			fi

			# Set search pattern based on bitrate
			search_pattern="*${bitrate}*"

			# Find and sort firmware files
			# mapfile -t options < <(
				# find . -maxdepth 1 -type f ! -name "*.md" -name "$search_pattern" -printf "%f\n" | sort_firmware_files
			# )
			
			archive_dir="$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/survey" # Corrected path
			if [[ -d $archive_dir ]]; then
				# Get the folder names sorted from largest to smallest version
				folders=($(ls -d "$archive_dir"/*/ | sort -rV))

				for folder in "${folders[@]}"; do
					if [[ -d "$folder" ]]; then
						folder_name=$(basename "$folder")
						# List the files inside each folder using the same search pattern
						for file in "$folder"/$search_pattern; do
							if [[ -f "$file" ]]; then
								options+=("${folder_name}/$(basename "$file")")
							fi
						done
					fi
				done
			fi
		fi

		# Add "Back" option
		options+=("Back")

		# Display select menu
		COLUMNS=12
		PS3="Please select a firmware to flash: "
		select opt in "${options[@]}"; do
			case $opt in
				*.bin)
					flashing "$opt" "$1" "klippy"
					break
					;;
				"Back")
					menu
					break
					;;
				*)
					echo "Invalid selection. Please try again."
					;;
			esac
		done
	fi
	options=()
	if [[ -n $queryID ]] && [[ $2 == 4 ]] && [[ $usbID == "" ]]; then
		# Retrieve CANBus bitrate
		bitrate=$(ip -s -d link show can0 | grep -oP 'bitrate\s\K\w+')
		printf "Your Host CANBus is configured at ${RED}Bitrate: $bitrate${NC}\n"
		printf "${BLUE}Flashing ${queryID} via ${GREEN}CANBUS - KATAPULT${NC}\n\n"

		# Update repository
		cd "$CARTOGRAPHER_KLIPPER_DIR" || exit

		# Determine flashing type
		if [[ $ftype == "katapult" ]]; then
			cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/katapult-deployer" || exit

			# Set search parameters based on switch
			if [[ $switch == "canbus" ]]; then
				exclude_pattern="*usb*"
			elif [[ $switch == "usb" ]]; then
				include_pattern="*usb*"
			else
				include_pattern="*"
			fi

			# Find and sort firmware files
			mapfile -t options < <(
				find . -maxdepth 1 -type f ! -name "*.txt" \( \
					${include_pattern:+-name "$include_pattern"} \
					${exclude_pattern:+! -name "$exclude_pattern"} \
				\) -printf "%f\n" | sort_firmware_files
			)

		else
			# Set directory based on parameter
			if [[ $1 == 1 ]]; then
				cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/survey" || exit
			else
				cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3" || exit
			fi

			# Set search pattern based on bitrate
			search_pattern="*${bitrate}*"

			# # Find and sort firmware files
			# mapfile -t options < <(
				# find . -maxdepth 1 -type f ! -name "*.md" -name "$search_pattern" -printf "%f\n" | sort_firmware_files
			# )
			
			archive_dir="$CARTOGRAPHER_KLIPPER_DIR/cartographer-klipper/firmware/v2-v3/survey" # Corrected path
			if [[ -d $archive_dir ]]; then
				# Get the folder names sorted from largest to smallest version
				folders=($(ls -d "$archive_dir"/*/ | sort -rV))

				for folder in "${folders[@]}"; do
					if [[ -d "$folder" ]]; then
						folder_name=$(basename "$folder")
						# List the files inside each folder using the same search pattern
						for file in "$folder"/$search_pattern; do
							if [[ -f "$file" ]]; then
								options+=("${folder_name}/$(basename "$file")")
							fi
						done
					fi
				done
			fi
		fi

		# Add "Back" option
		options+=("Back")

		# Display select menu
		COLUMNS=12
		PS3="Please select a firmware to flash: "
		select opt in "${options[@]}"; do
			case $opt in
				*.bin)
					flashing "$opt" "$1" "query"
					break
					;;
				"Back")
					menu
					break
					;;
				*)
					echo "Invalid selection. Please try again."
					;;
			esac
		done
	fi
	options=()
	# If found device is DFU
	if [[ $dfuID != "" ]] && [[ $2 == 2 ]]; then
		printf "${BLUE}Flashing via ${GREEN}DFU${NC}\n\n"
		search_pattern="Full_Survey_*"

		archive_dir="$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/combined-firmware" # Corrected path
		if [[ -d $archive_dir ]]; then
			# Get the folder names sorted from largest to smallest version
			cd $archive_dir
			folders=($(ls -d "$archive_dir"/*/ | sort -rV))

			for folder in "${folders[@]}"; do
				if [[ -d "$folder" ]]; then
					folder_name=$(basename "$folder")
					# List the files inside each folder using the same search pattern
					for file in "$folder"/$search_pattern; do
						if [[ -f "$file" ]]; then
							options+=("${folder_name}/$(basename "$file")")
						fi
					done
				fi
			done
		fi
		
		# Add "Back" option
		options+=("Back")
		
		#done < <(find $DIRECTORY -maxdepth 1 -type f  \( -name 'katapult_and_carto_can_1m_beta.bin' \)  -print0)
		COLUMNS=12
		PS3="Please select a firmware to flash: "
		select opt in "${options[@]}"; do
			case $opt in
				*.bin)
					flashing "$opt" "$1" "dfu"
					break
					;;
				"Back")
					menu
					break
					;;
				*)
					echo "Invalid selection. Please try again."
					;;
			esac
		done
	fi
	options=()
	# If found device is USB
	if [[ -n $usbID ]] && [[ $2 == 3 ]]; then
		printf "${BLUE}Flashing via ${GREEN}USB - KATAPULT${NC}\n\n"

		# Update repository

		cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/katapult-deployer" || exit

		if [[ $ftype == "katapult" ]]; then
			cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/katapult-deployer" || exit

			# Set search parameters based on switch
			if [[ $switch == "canbus" ]]; then
				exclude_pattern="*USB*"
			elif [[ $switch == "usb" ]]; then
				include_pattern="*USB*"
			else
				include_pattern="*"
			fi

			# Find and sort firmware files
			mapfile -t options < <(
				find . -maxdepth 1 -type f ! -name "*.txt" \( \
					${include_pattern:+-name "$include_pattern"} \
					${exclude_pattern:+! -name "$exclude_pattern"} \
				\) -printf "%f\n" | sort_firmware_files
			)

		else
			# Set directory based on parameter
			if [[ $1 == 1 ]]; then
				cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/survey" || exit
			else
				cd "$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/" || exit
			fi

			# Set search pattern based on USB
			search_pattern="*USB*"

			# Find and sort firmware files
			# mapfile -t options < <(
				# find . -maxdepth 1 -type f ! -name "*.md" -name "$search_pattern" -printf "%f\n" | sort_firmware_files
			# )
			
			archive_dir="$CARTOGRAPHER_KLIPPER_DIR/firmware/v2-v3/survey" # Corrected path
			if [[ -d $archive_dir ]]; then
				# Get the folder names sorted from largest to smallest version
				folders=($(ls -d "$archive_dir"/*/ | sort -rV))

				for folder in "${folders[@]}"; do
					if [[ -d "$folder" ]]; then
						folder_name=$(basename "$folder")
						# List the files inside each folder using the same search pattern
						for file in "$folder"/$search_pattern; do
							if [[ -f "$file" ]]; then
								options+=("${folder_name}/$(basename "$file")")
							fi
						done
					fi
				done
			fi
		fi

		# Add "Back" option
		options+=("Back")

		# Display select menu
		COLUMNS=12
		PS3="Please select a firmware to flash: "
		select opt in "${options[@]}"; do
			case $opt in
				*.bin)
					flashing "$opt" "$1" "usb"
					break
					;;
				"Back")
					menu
					break
					;;
				*)
					echo "Invalid selection. Please try again."
					;;
			esac
		done
	fi
	read -p "Press enter to continue"
}

flashing(){
	# Flash Device FUNCTION
	header;
	survey=$2
	firmwareFile=$(echo "$1" | sed 's|^./||')
	folder_name=$(echo "$firmwareFile" | cut -d'/' -f1)
	reference_version="5.0.0"
	# Compare the folder name (version) to the reference version
	if [[ $(printf "%s\n" "$folder_name" "$reference_version" | sort -V | head -n 1) != "$folder_name" ]]; then
		echo
		echo
		printf "${RED}WARNING:${NC} For Firmware Newer Than 5.0.0\n"
		printf "${GREEN}channel: stable${NC} needs to be set under ${BLUE}[update_manager cartographer]${NC} in your ${BLUE}moonraker.conf${NC}"
		echo
		echo "Please also, make sure you recalibrate."
		echo
		printf "Changelogs are available at ${BLUE}https://github.com/Cartographer3D/cartographer-klipper/releases${NC}\n\n"
		printf "${RED}###################################################################################${NC}\n"
		while true; do
		read -p "Do you wish to continue flashing? (yes/no) " yn < /dev/tty
		case $yn in
			[Yy]* ) break;;
			[Nn]* ) menu;;
			* ) echo "Please answer yes or no.";;
		esac
	done
	fi
	if [[ $3 == "query" ]]; then
		uuid=$queryID
	fi
	
	if [[ $3 == "klippy" ]]; then
		if [[ $canbootID != "" ]]; then
			uuid=$canbootID
		fi
		if [[ $katapultID != "" ]]; then
			uuid=$katapultID
		fi
	fi
	flashed=0
	if [[ $firmwareFile != "" ]]; then
		echo "Flashing with $firmwareFile ..."
		
		# Check if Katapult
		if [[ $canbootID != "" ]] || [[ $katapultID != "" ]] && [[ $3 == "klippy" ]] && [[ $flashed == 0 ]]; then
			echo "Flashing Device $uuid"
			# Flash Katapult Firmware
			python3 ~/katapult/scripts/flash_can.py -i can0 -f $firmwareFile -u $uuid;
			read -p "Press enter to continue"
			display_flashed $findUUID "can" $survey
			flashed=1
		fi
		
		# Check if Katapult
		if [[ $queryID != "" ]] && [[ $3 == "query" ]] && [[ $flashed == 0 ]]; then
			echo "Flashing Device $uuid"
			# Flash Katapult Firmware
			python3 ~/katapult/scripts/flash_can.py -i can0 -f $firmwareFile -u $uuid;
			read -p "Press enter to continue"
			display_flashed $findqueryUUID "can" $survey
			flashed=1
		fi
		
		# Check if DFU
		if [[ $dfuID != "" ]] && [[ $3 == "dfu" ]] && [[ $flashed == 0 ]]; then
			echo "Flashing DFU Device $dfuID"
			# Flash DFU Firmware
			sudo dfu-util --device ,$dfuID -R -a 0 -s 0x08000000:leave -D $firmwareFile
			read -p "Press enter to continue"
			display_flashed $dfuID "dfu" $survey
			flashed=1
		fi
		
		# Check if USB
		if [[ $usbID != "" ]] && [[ $3 == "usb" ]] && [[ $flashed == 0 ]]; then
			echo "Flashing USB Device $usbID"
			# FLash USB Firmware
			~/klippy-env/bin/python ~/klipper/lib/canboot/flash_can.py -f $firmwareFile -d /dev/serial/by-id/$usbID
			read -p "Press enter to continue"
			display_flashed $cartoID "usb" $survey
			flashed=1
		fi
		flashed="1"
		sudo service klipper restart
		read -p "Press enter to continue"
		menu;
	else
		echo "Firmware file not found to be flashed"
		flashed="0"
		read -p "Press enter to continue"
		menu;
	fi
}
display_flashed(){
	header;
	device=$1
	method=$2
	survey=$3
	
	printf "Your device has been flashed.
	
Note, after you exit this script you need to replace the serial path  or UUID with your probes serial path or UUID, this can be found by running the following commands 

For USB based probes\n\n"
	printf "${RED}ls /dev/serial/by-id/${NC}-\n"
	printf "For CAN based probes\n\n"
	printf "${RED}~/klippy-env/bin/python ~/klipper/scripts/canbus_query.py can0${NC}-\n"
	printf "Take note of either the Serial ID or the UUID.\n\n"
	read -p "Press enter to continue"
	delete_temp;
}
delete_temp(){
	if [[ -d "$TEMP_DIR" ]]; then
		echo "Cleaning up temporary directory..."
		rm -rf "$temp_dir"
		echo "Temporary directory deleted."
	fi
	exit;
}
disclaimer;

initialChecks;

menu;





