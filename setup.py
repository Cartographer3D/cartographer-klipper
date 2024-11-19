import os
import re
import glob
import argparse
import subprocess
import shutil
import zipfile
from datetime import datetime

# Paths and configuration setup
config_file_path = os.path.expanduser("~/printer_data/config/printer.cfg")
klippy_log_path = os.path.expanduser("~/printer_data/logs/klippy.log")

# Define the headers to comment out
headers_to_comment = [
    "scanner",
    "cartographer",
    "adxl345",
    "resonance_tester",
    "lis2dw",
    "bed_mesh",
    "probe",
    "temperature_sensor Cartographer_MCU",
]

# Define keywords to search for
keywords_to_delete = ["scanner", "cartographer", "probe"]

# Set the debug flag to True or False to enable/disable debug output
debug = False  # Set to False to disable debugging messages


def debug_print(message):
    """Print debug messages if debugging is enabled."""
    if debug:
        print(message)


# Function to create a backup ZIP archive with a timestamp
def create_backup_zip(main_file, include_files):
    # Display formatted heading
    if debug:
        print("\n" + "=" * 60)
        print(" Creating Backup Zip File ".center(60, "="))
        print("=" * 60 + "\n")

    # Generate a timestamped filename for the backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_zip_path = os.path.expanduser(
        f"~/printer_data/config/cfgbackup_{timestamp}.zip"
    )

    with zipfile.ZipFile(backup_zip_path, "w") as backup_zip:
        # Add the main config file
        backup_zip.write(main_file, os.path.basename(main_file))

        # Add each included file if it exists
        for file_path in include_files:
            if os.path.exists(file_path):
                backup_zip.write(file_path, os.path.basename(file_path))
                debug_print(f"Added {file_path} to backup.")

    debug_print(f"Backup created at {backup_zip_path}.")


# Function to comment out headers and their sections in a given file
def comment_headers_in_file(file_path):
    # Display formatted heading and headers list
    if debug:
        print("\n" + "=" * 60)
        print(" Commenting Out Specified Headers ".center(60, "="))
        print("=" * 60 + "\n")
        print(f"Processing file: {file_path}")
        print("\nHeaders to comment out:")
        for header in headers_to_comment:
            print(f" - [{header}]")
        print("\n" + "-" * 60 + "\n")

    with open(file_path, "r") as file:
        lines = file.readlines()

    in_section = {header: False for header in headers_to_comment}
    updated_lines = []
    lines_commented = False

    # Create regex patterns for headers
    header_patterns = {
        header: re.compile(r"^\[" + re.escape(header) + r"\b")
        for header in headers_to_comment
    }
    section_header_pattern = re.compile(r"^\[.*\]")

    for line in lines:
        for header, pattern in header_patterns.items():
            if pattern.match(line):
                in_section[header] = True
                # Comment out the header line if it is not already commented
                if not line.strip().startswith("#"):
                    updated_lines.append("#" + line)
                    lines_commented = True
                else:
                    updated_lines.append(
                        line
                    )  # Keep the line as is if already commented
                break
        else:
            if any(in_section.values()):
                if section_header_pattern.match(line):
                    # A new section header is found; reset the section flags
                    for header in headers_to_comment:
                        in_section[header] = False
                    updated_lines.append(
                        line
                    )  # Append the new section header without commenting
                else:
                    # Comment out non-header lines (uncommented or already commented)
                    if not line.strip().startswith("#"):
                        updated_lines.append(
                            "#" + line
                        )  # Commenting out the line if not already commented
                        lines_commented = True
                    else:
                        updated_lines.append(
                            line
                        )  # Keep the line as is if already commented
            else:
                updated_lines.append(line)

    if lines_commented:
        with open(file_path, "w") as file:
            file.writelines(updated_lines)
        debug_print(
            f"Updated {file_path}: Commented out lines in the specified sections."
        )
    else:
        debug_print(f"No lines were commented out in {file_path}.")


# Function to delete lines starting with #*# and containing specified keywords
def delete_scanner_lines(file_path, keywords):
    # Display formatted heading and keywords list
    if debug:
        print("\n" + "=" * 60)
        print(" Deleting Specified Sections and Lines ".center(60, "="))
        print("=" * 60 + "\n")
        print(f"Processing file: {file_path}")
        print("\nKeywords to delete sections containing:")
        for keyword in keywords_to_delete:
            print(f" - {keyword}")
        print("\n" + "-" * 60 + "\n")
    with open(file_path, "r") as file:
        lines = file.readlines()

    updated_lines = []
    deleted_lines = []  # To store lines that are actually deleted
    skip_lines = False

    for line in lines:
        # Check if the line starts with #*# and contains any of the keywords
        if line.startswith("#*#") and any(keyword in line for keyword in keywords):
            skip_lines = True  # Start skipping lines
            deleted_lines.append(line)  # Track the deleted line
            continue  # Skip this line

        # If we are skipping lines and encounter a new header, stop skipping
        if skip_lines and re.match(r"^\[.*\]", line):
            skip_lines = False  # Stop skipping when a new header is found
            updated_lines.append(line)  # Include this header in the updated lines
            continue  # Continue to process other lines

        # If not skipping, add the line to updated lines
        if not skip_lines:
            updated_lines.append(line)
        elif skip_lines:
            # Track lines within the section to be deleted
            deleted_lines.append(line)

    # Write the updated lines back to the file
    with open(file_path, "w") as file:
        file.writelines(updated_lines)

    # Display deleted lines only if any were actually deleted
    if deleted_lines:
        debug_print(f"\nDeleted lines from {file_path}:")
        for deleted_line in deleted_lines:
            if debug:
                print(deleted_line, end="")  # Print each deleted line
    else:
        debug_print(f"No lines deleted from {file_path}.")


# Function to search for .cfg files in a directory and its subdirectories
def find_cfg_files(base_path):
    return [
        os.path.join(dirpath, f)
        for dirpath, _, files in os.walk(base_path)
        for f in files
        if f.endswith(".cfg")
    ]


# Function to process includes in printer.cfg
def process_includes(base_path):
    included_files = []
    with open(base_path, "r") as file:
        lines = file.readlines()

    for line in lines:
        line = line.strip()
        if line.startswith("[include"):
            include_pattern = line.split(" ", 1)[1].strip().strip("[]")
            include_path = os.path.dirname(base_path)

            if "*" in include_pattern:
                included_files += glob.glob(os.path.join(include_path, include_pattern))
            else:
                included_file = os.path.join(include_path, include_pattern)
                if os.path.exists(included_file):
                    included_files.append(included_file)

    return list(set(included_files))  # Unique list of included files


# Function to get position_max values from stepper_x and stepper_y in included .cfg files
def get_position_max():
    base_dir = os.path.dirname(config_file_path)

    # Prepare a list to store configuration files
    cfg_files = []

    # Check for printer.cfg and prioritize it
    printer_cfg_path = os.path.join(base_dir, "printer.cfg")
    if os.path.exists(printer_cfg_path):
        cfg_files.append(printer_cfg_path)  # Add printer.cfg first

    # Add other config files found
    cfg_files += find_cfg_files(base_dir)
    # Add included files
    cfg_files += process_includes(config_file_path)

    # Ensure we have a unique list of configuration files
    cfg_files = list(set(cfg_files))  # Remove duplicates if any

    # Sort the cfg_files list, ensuring printer.cfg is still at the front
    cfg_files.sort()  # Sort the remaining files alphabetically
    if printer_cfg_path in cfg_files:
        cfg_files.remove(printer_cfg_path)  # Remove printer.cfg from sorted list
        cfg_files.insert(0, printer_cfg_path)  # Insert printer.cfg at the start

    position_max = {"x": None, "y": None}
    if debug:
        print("\n" + "=" * 60)
        print(" Debugging Output for get_position_max ".center(60, "="))
        print("=" * 60 + "\n")
        print("Searching in the following configuration files:")
        for file in cfg_files:
            print(f"  - {file}")

    for file_path in cfg_files:
        if debug:
            print(f"\nProcessing file: {file_path}")
        with open(file_path, "r") as file:
            current_stepper = None
            for line in file:
                line = line.strip()
                if line.startswith("[stepper_x]"):
                    current_stepper = "x"
                    if debug:
                        print("Found [stepper_x] section.")
                elif line.startswith("[stepper_y]"):
                    current_stepper = "y"
                    if debug:
                        print("Found [stepper_y] section.")
                elif current_stepper and line.startswith("position_max:"):
                    pos_value = float(line.split(":")[1].strip())
                    position_max[current_stepper] = pos_value
                    if debug:
                        print(f"Found position_max for {current_stepper}: {pos_value}")
                    current_stepper = None
                if all(position_max.values()):
                    if debug:
                        print("Both position_max values found; exiting loop early.")
                    break
            # Check after processing a file if both values are found
        if all(position_max.values()):
            break  # Exit outer loop

    if None in position_max.values():
        raise ValueError(
            "Could not find position_max values for stepper_x and stepper_y in included files."
        )

    x_mid, y_mid = position_max["x"] / 2, position_max["y"] / 2
    if debug:
        print("\nFinal position_max values:")
        print(f"  stepper_x: {position_max['x']}, stepper_y: {position_max['y']}")
        print(f"  Midpoints: x_mid: {x_mid}, y_mid: {y_mid}")
        print(
            f"  Adjusted values: x_adjusted: {position_max['x'] - 50}, y_adjusted: {position_max['y'] - 50}"
        )
        print("=" * 60)
    return x_mid, y_mid, position_max["x"] - 50, position_max["y"] - 50


# Function to get the canbus_uuid from canbus_query.py
def get_canbus_uuid(show=False):
    python_path = os.path.expanduser("~/klippy-env/bin/python")
    script_path = os.path.expanduser("~/klipper/scripts/canbus_query.py")

    if debug and show:
        print("\n" + "=" * 60)
        print(" Debugging Output for get_canbus_uuid ".center(60, "="))
        print("=" * 60 + "\n")
        print(f"Checking Python executable at: {python_path}")
        print(f"Script path: {script_path}")

    # Check if the Python executable exists
    if not os.path.exists(python_path):
        raise FileNotFoundError(f"Python executable not found at {python_path}")

    try:
        if debug and show:
            print("Executing canbus_query.py...")
        result = subprocess.run(
            [python_path, script_path, "can0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        output = result.stdout
        if debug and show:
            print("Script executed successfully. Output received:")
            print(output)
        uuids = re.findall(r"canbus_uuid=([0-9a-f]+)", output)
        if debug:
            if uuids:
                print(f"UUIDs found: {uuids}")
            else:
                print("No UUIDs found in the output.")
        return uuids if uuids else None
    except subprocess.CalledProcessError as e:
        print(f"Error executing canbus_query.py: {e.stderr.strip()}")
        return None


# Function to check if any canbus_uuid is in klippy.log
def check_canbus_in_log(canbus_uuids):
    if debug:
        print("\n" + "=" * 60)
        print(" Debugging Output for check_canbus_in_log ".center(60, "="))
        print("=" * 60 + "\n")
        print(
            f"Checking for canbus_uuid: {canbus_uuids} in log file: {klippy_log_path}"
        )

    try:
        with open(klippy_log_path, "r") as log_file:
            log_content = log_file.read()
            if debug:
                print("Log file read successfully.")
                print(f"Log content length: {len(log_content)} characters.")

            # Check if any UUID in the list is found in the log content
            found = any(uuid in log_content for uuid in canbus_uuids)

            if debug:
                if found:
                    print(f"One or more canbus_uuids found in the log.")
                else:
                    print("No canbus_uuids found in the log.")

            return found
    except FileNotFoundError:
        print(f"Log file not found at: {klippy_log_path}")
        return False
    except Exception as e:
        print(f"An error occurred while reading the log file: {str(e)}")
        return False


# Function to find Cartographer serial IDs
def find_cartographer_serial_id():
    serial_dir = "/dev/serial/by-id"
    try:
        serial_ids = [f for f in os.listdir(serial_dir) if "Cartographer" in f]
        return os.path.join(serial_dir, serial_ids[0]) if serial_ids else None
    except FileNotFoundError:
        print(f"Directory {serial_dir} not found.")
        return None


# Function to create a backup of the configuration file
def backup_config_file():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file_path = os.path.expanduser(
        f"~/printer_data/config/printer.cfg.bak_{timestamp}"
    )
    shutil.copy(config_file_path, backup_file_path)
    print(f"Backup of printer.cfg created at {backup_file_path}")


# Function to add configuration lines based on probe type
def add_probe_config(probe_type):
    if debug:
        # Heading with consistent formatting
        print("\n" + "=" * 60)
        print(f" Debugging Output for add_probe_config ".center(60, "="))
        print("=" * 60 + "\n")
        print(f"Adding configuration for probe type: touch")

        print("Configuring settings for touch probe...")

    # backup_config_file()  # Backup the config file before editing

    with open(config_file_path, "r") as config_file:
        lines = config_file.readlines()

    scanner_exists = any(line.strip().startswith("[scanner]") for line in lines)
    cartographer_exists = any(
        line.strip().startswith("[cartographer]") for line in lines
    )

    # Adding [scanner] section for touch probe type
    if not scanner_exists and not cartographer_exists:
        canbus_uuid = get_canbus_uuid()

        serial_entry = "#serial: /dev/serial/by-id/ # CHANGE ME FOR USB"
        canbus_entry = "#canbus_uuid:  # CHANGE ME FOR CANBUS"

        if canbus_uuid and not check_canbus_in_log(canbus_uuid):
            canbus_entry = f"canbus_uuid: {canbus_uuid}"
        else:
            serial_id = find_cartographer_serial_id()
            if serial_id:
                serial_entry = f"serial: {serial_id}"
                canbus_entry = "#canbus_uuid: # CHANGE ME FOR CANBUS"

        # Scanner config lines
        config_lines = f"""
[scanner]
{serial_entry}            
{canbus_entry}
#
#   Visit the link below for help finding your device ID
#   https://docs.cartographer3d.com/cartographer-probe/installation-and-setup/classic-installation/klipper-setup#finding-the-serial-or-uuid
#        
x_offset: 0              
#    adjust for your cartographers offset from nozzle to middle of coil            
y_offset: 15        
#    adjust for your cartographers offset from nozzle to middle of coil 
#    Offsets are measured from the centre of your coil, to the tip of your nozzle 
#    on a level axis. It is vital that this is accurate.                 
backlash_comp: 0.5
#   Backlash compensation distance for removing Z backlash before measuring
#   the sensor response.
sensor: cartographer
#    this must be set as cartographer unless using IDM etc.
sensor_alt: carto
#    alternate name to call commands. CARTO_TOUCH etc    
mode: {probe_mode} 
mesh_runs: 2
#    Number of mesh runs to complete a BED_MESH_CALIBRATE

[temperature_sensor Cartographer_MCU]
sensor_type:   temperature_mcu
sensor_mcu:            scanner
min_temp:                    0
max_temp:                  105
"""

        # Bed mesh section for touch probe type
        bed_mesh_lines = f"""
[bed_mesh]
zero_reference_position: {x_mid}, {y_mid}   
#    set this to the middle of your bed 
speed: 200
#    movement speed of toolhead during bed mesh
horizontal_move_z: 5
#    height of scanner during bed mesh scan
mesh_min: 50, 50
#    start point of bed mesh [X, Y].
mesh_max: {x_mesh_max}, {y_mesh_max}
#    end point of bed mesh [X, Y]
probe_count: 30, 30
algorithm: bicubic
"""

        # Insert the scanner and bed mesh config lines
        insert_index = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("[include"):
                insert_index = i + 1

        lines.insert(insert_index, config_lines)
        lines.insert(insert_index + 1, bed_mesh_lines)

        # Adding [adxl345] and [resonance_tester] sections for touch probe type
        adxl345_lines = f"""
[adxl345]
cs_pin: scanner:PA3
spi_bus: spi1
"""

        resonance_tester_lines = f"""
[resonance_tester]
accel_chip: adxl345
probe_points:
    {x_mid}, {y_mid}, 20
"""

        # Insert the adxl345 and resonance_tester config lines
        lines.insert(insert_index + 2, adxl345_lines)
        lines.insert(insert_index + 3, resonance_tester_lines)

        # Write the updated lines back to the configuration file
        with open(config_file_path, "w") as config_file:
            config_file.writelines(lines)

        debug_print(f"[scanner] section added to printer.cfg successfully.")
    else:
        debug_print(f"No updates made: Configuration already exists.")


# Function to update the [stepper_z] section
def update_stepper_z():
    all_cfg_files = [config_file_path] + process_includes(config_file_path)

    for file_path in all_cfg_files:
        # print(f"Processing file: {file_path}")
        with open(file_path, "r") as file:
            lines = file.readlines()

        updated_lines = []
        inside_stepper_z = False
        endstop_pin_updated = False
        homing_retract_updated = False
        stepper_z_found = False
        position_endstop_commented = False

        for line in lines:
            stripped_line = line.strip()

            if stripped_line.startswith("[stepper_z]"):
                inside_stepper_z = True
                stepper_z_found = True
                updated_lines.append(line)  # Keep the [stepper_z] line
                debug_print(f"Found [stepper_z] section.")  # Debugging output
            elif inside_stepper_z and stripped_line == "":
                # End of [stepper_z] section
                inside_stepper_z = False
                debug_print(f"Exiting [stepper_z] section.")  # Debugging output
                # Add new lines if they haven't been added
                if not endstop_pin_updated:
                    updated_lines.append(
                        "endstop_pin: probe:z_virtual_endstop # uses cartographer as virtual endstop\n"
                    )
                    endstop_pin_updated = True
                    debug_print(f"Added endstop_pin line.")  # Debugging output
                if not homing_retract_updated:
                    updated_lines.append(
                        "homing_retract_dist: 0 # cartographer needs this to be set to 0\n"
                    )
                    homing_retract_updated = True
                    debug_print(f"Added homing_retract_dist line.")  # Debugging output
                updated_lines.append("")  # Blank line for separation
            else:
                if inside_stepper_z:
                    # Check for existing lines to update
                    if "endstop_pin:" in stripped_line and not endstop_pin_updated:
                        updated_lines.append(
                            "endstop_pin: probe:z_virtual_endstop # uses cartographer as virtual endstop\n"
                        )
                        endstop_pin_updated = True
                        debug_print(f"Updated endstop_pin line.")  # Debugging output
                    elif (
                        "homing_retract_dist:" in stripped_line
                        and not homing_retract_updated
                    ):
                        updated_lines.append(
                            "homing_retract_dist: 0 # cartographer needs this to be set to 0\n"
                        )
                        homing_retract_updated = True
                        debug_print(
                            f"Updated homing_retract_dist line."
                        )  # Debugging output
                    elif stripped_line.startswith("position_endstop:"):
                        # Check if it's already commented out
                        if not stripped_line.startswith("#"):
                            updated_lines.append(
                                "#" + stripped_line + "\n"
                            )  # Comment out the existing line
                            position_endstop_commented = True
                            debug_print(
                                f"Commented out position_endstop line."
                            )  # Debugging output
                        else:
                            updated_lines.append(
                                line
                            )  # Keep the original line if it's already commented
                    else:
                        updated_lines.append(
                            line
                        )  # Always add the line if not in stepper_z
                else:
                    updated_lines.append(
                        line
                    )  # Always add the line if not in stepper_z
        # Write the updated lines back to the file if changes were made
        if stepper_z_found and (endstop_pin_updated or homing_retract_updated):
            with open(file_path, "w") as file:
                file.writelines(updated_lines)
            debug_print(f"Updated [stepper_z] section in {file_path}.")
            break
        else:
            if stepper_z_found:
                debug_print(f"No updates made to [stepper_z] section in {file_path}.")
            # else:
            # print("[stepper_z] section not found in this file.")

    if not stepper_z_found:
        debug_print(f"[stepper_z] section not found in any configuration files.")


def add_safe_z_home():
    # Only process the main printer.cfg file
    base_path = config_file_path

    # Find all relevant configuration files
    included_files = process_includes(base_path)
    included_files.append(base_path)  # Include the main file

    # Check for existing sections in all relevant configuration files
    homing_override_found = False
    safe_z_home_found = False

    for file in included_files:
        with open(file, "r") as f:
            lines = f.readlines()
            if any(
                "[homing_override]" in line and not line.strip().startswith("#")
                for line in lines
            ):
                homing_override_found = True
            if any(
                "[safe_z_home]" in line and not line.strip().startswith("#")
                for line in lines
            ):
                safe_z_home_found = True

    # Only add if [homing_override] is not found
    if not homing_override_found:
        # Create the safe_z_home entry
        safe_z_home_entry = f"\n[safe_z_home]\nhome_xy_position: {x_mid}, {y_mid} # Center position\nz_hop: 10\n"

        # Read the main printer.cfg file
        with open(base_path, "r") as f:
            lines = f.readlines()

        updated_lines = []
        last_include_index = -1  # Track the last index of [include]

        for i, line in enumerate(lines):
            updated_lines.append(line)
            if "[include" in line:
                last_include_index = len(
                    updated_lines
                )  # Update the last index for [include]

        # If there was at least one [include] section, add safe_z_home after it
        if last_include_index != -1:
            # Add safe_z_home_entry after the last [include] if it doesn't exist
            if not safe_z_home_found:
                updated_lines.insert(
                    last_include_index, safe_z_home_entry
                )  # Add safe_z_home after the last [include]

                # Write back to the main printer.cfg file
                with open(base_path, "w") as f:
                    f.writelines(updated_lines)
                debug_print(
                    f"Added [safe_z_home] section after the last [include] section in {base_path}."
                )
            else:
                debug_print(
                    f"[safe_z_home] section already exists (commented or active)."
                )
        else:
            debug_print(
                f"[safe_z_home] section was not added because no [include] sections were found."
            )
    else:
        debug_print(f"[homing_override] section exists; [safe_z_home] not added.")


# Function to find lines containing UUIDs in the log file
def find_uuid_lines_in_log(canbus_uuids):
    if debug:
        print("\n" + "=" * 60)
        print(" Debugging Output for find_uuid_lines_in_log ".center(60, "="))
        print("=" * 60 + "\n")
        print(
            f"Searching for canbus_uuid: {canbus_uuids} in log file: {klippy_log_path}"
        )

    found_lines = []
    section_headers = []

    try:
        with open(klippy_log_path, "r") as log_file:
            log_lines = log_file.readlines()  # Read the log file line by line
            if debug:
                print("Log file read successfully.")
                print(f"Total lines in log: {len(log_lines)}")

            # Loop through each line to find UUIDs and their section
            for i, line in enumerate(log_lines):
                # Check if the line contains a section header
                if line.startswith("[") and line.endswith("]\n"):
                    section_headers.append(line.strip())  # Add the section header

                # Search for each UUID in the line
                for uuid in canbus_uuids:
                    if uuid in line:
                        # Get the last three section headers (if available)
                        last_sections = section_headers[
                            -3:
                        ]  # Get the last three section headers

                        # Check if any of the last sections are "scanner" or "cartographer"
                        is_relevant_section = any(
                            "scanner" in section.lower()
                            or "cartographer" in section.lower()
                            for section in last_sections
                        )

                        # Only add the line if it's under a relevant section
                        if is_relevant_section:
                            colored_line = (
                                f"\033[32m{line.strip()}\033[0m"  # Color the line green
                            )
                            found_lines.append((colored_line, last_sections))
                            break  # No need to check other UUIDs for this line

            if debug:
                if found_lines:
                    print(
                        f"Found {len(found_lines)} relevant lines with UUIDs in the log."
                    )
                else:
                    print(
                        "No relevant lines found with the specified canbus_uuids in the log."
                    )

            return found_lines

    except FileNotFoundError:
        print(f"Log file not found at: {klippy_log_path}")
        return []
    except Exception as e:
        print(f"An error occurred while reading the log file: {str(e)}")
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Install probe configuration in printer.cfg"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug mode for detailed output"
    )
    parser.add_argument(
        "--mode",
        choices=["touch", "scan"],
        required=True,
        help="Specify the probe mode: 'touch' or 'scan'"
    )
    args = parser.parse_args()
    debug = args.debug
    probe_mode = args.mode
    try:
        x_mid, y_mid, x_mesh_max, y_mesh_max = get_position_max()
        included_files = process_includes(config_file_path)
        create_backup_zip(config_file_path, included_files)
        comment_headers_in_file(config_file_path)
        delete_scanner_lines(config_file_path, keywords_to_delete)
        for included_file in included_files:
            comment_headers_in_file(included_file)
            delete_scanner_lines(included_file, keywords_to_delete)
        add_probe_config(args.mode)
        update_stepper_z()
        add_safe_z_home()

        # Inform the user of the configuration changes
        print("\n" + "=" * 60)
        print(" Configuration Update Complete ".center(60, "="))
        print("=" * 60 + "\n")
        # Get the canbus UUIDs
        canbus_uuids = get_canbus_uuid(True)

        # Check if UUIDs were retrieved successfully
        if canbus_uuids:
            # Find and display the lines in the log that contain the UUIDs
            uuid_lines = find_uuid_lines_in_log(canbus_uuids)
            for line, sections in uuid_lines:
                # Print the section headers followed by the colored line
                for section in sections:
                    print(section)
                print(line)  # Output the line with potential green color
                print()  # Add spacing between entries for readability

        print(
            "All previous instances of 'cartographer' or 'scanner' have been commented out or removed from your configuration files."
        )
        print(
            "Your Klipper configuration in 'printer.cfg' has had the necessary settings for cartographer/scanner added and configured to your printer.\n"
        )
        print(
            "⚠️  Please double-check the configuration before proceeding by following the link below.\n"
        )

        print("🔗 Touch Mode Setup:")
        print("   Please visit:")
        print(
            "   https://docs.cartographer3d.com/cartographer-probe/installation-and-setup/klipper-configuation"
        )

        print("\n" + "=" * 60)
        print(" End of Instructions ".center(60, "="))
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"An error occurred: {e}")
