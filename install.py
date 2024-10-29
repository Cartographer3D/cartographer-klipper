import os
import re
import glob
import argparse
import subprocess
import shutil
from datetime import datetime

# Paths and configuration setup
config_file_path = os.path.expanduser("~/printer_data/config/printer.cfg")
klippy_log_path = os.path.expanduser("~/printer_data/logs/klippy.log")

# Function to search for .cfg files in a directory and its subdirectories
def find_cfg_files(base_path):
    return [os.path.join(dirpath, f)
            for dirpath, _, files in os.walk(base_path)
            for f in files if f.endswith('.cfg')]

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
    cfg_files = find_cfg_files(base_dir) + process_includes(config_file_path)
    position_max = {"x": None, "y": None}
    
    for file_path in cfg_files:
        with open(file_path, "r") as file:
            current_stepper = None
            for line in file:
                line = line.strip()
                if line.startswith("[stepper_x]"):
                    current_stepper = "x"
                elif line.startswith("[stepper_y]"):
                    current_stepper = "y"
                elif current_stepper and line.startswith("position_max:"):
                    pos_value = float(line.split(":")[1].strip())
                    position_max[current_stepper] = pos_value
                    current_stepper = None
                if all(position_max.values()):
                    break

    if None in position_max.values():
        raise ValueError("Could not find position_max values for stepper_x and stepper_y in included files.")
    
    x_mid, y_mid = position_max["x"] / 2, position_max["y"] / 2
    return x_mid, y_mid, position_max["x"] - 50, position_max["y"] - 50

# Function to get the canbus_uuid from canbus_query.py
def get_canbus_uuid():
    python_path = os.path.expanduser("~/klippy-env/bin/python")
    script_path = os.path.expanduser("~/klipper/scripts/canbus_query.py")
    
    # Check if the Python executable exists
    if not os.path.exists(python_path):
        raise FileNotFoundError(f"Python executable not found at {python_path}")

    try:
        result = subprocess.run(
            [python_path, script_path, "can0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        output = result.stdout
        uuids = re.findall(r'canbus_uuid=([0-9a-f]+)', output)
        
        return uuids[0] if uuids else None
    except subprocess.CalledProcessError as e:
        print(f"Error executing canbus_query.py: {e.stderr.strip()}")
        return None

# Function to check if canbus_uuid is in klippy.log
def check_canbus_in_log(canbus_uuid):
    with open(klippy_log_path, "r") as log_file:
        return canbus_uuid in log_file.read()

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
    backup_file_path = os.path.expanduser(f"~/printer_data/config/printer.cfg.bak_{timestamp}")
    shutil.copy(config_file_path, backup_file_path)
    print(f"Backup of printer.cfg created at {backup_file_path}")

# Function to add configuration lines based on probe type
def add_probe_config(probe_type):
    backup_config_file()  # Backup the config file before editing
    
    with open(config_file_path, "r") as config_file:
        lines = config_file.readlines()

    scanner_exists = any(line.strip().startswith("[scanner]") for line in lines)
    cartographer_exists = any(line.strip().startswith("[cartographer]") for line in lines)

    # Adding [scanner] section for touch probe type
    if probe_type == "touch" and not scanner_exists and not cartographer_exists:
        x_mid, y_mid, x_mesh_max, y_mesh_max = get_position_max()
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
y_offset: 15                         
backlash_comp: 0.5
calibration_method: touch
sensor: cartographer
sensor_alt: carto
scanner_touch_z_offset: 0.05         
mesh_runs: 2

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
speed: 200
horizontal_move_z: 5
mesh_min: 35, 6
mesh_max: {x_mesh_max}, {y_mesh_max}
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

        print(f"[scanner] section added to printer.cfg successfully.")

    # Adding [cartographer] section for scan probe type
    elif probe_type == "scan" and not cartographer_exists and not scanner_exists:
        x_mid, y_mid, x_mesh_max, y_mesh_max = get_position_max()
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

        # Cartographer config lines
        cartographer_config_lines = f"""
[cartographer]
{serial_entry}
{canbus_entry}
#
#   Visit the link below for help finding your device ID
#   https://docs.cartographer3d.com/cartographer-probe/installation-and-setup/classic-installation/klipper-setup#finding-the-serial-or-uuid
#  
speed: 40.0
lift_speed: 5.0
backlash_comp: 0.5
x_offset: 0.0
y_offset: 21.1
trigger_distance: 2.0
trigger_dive_threshold: 1.5
trigger_hysteresis: 0.006
cal_nozzle_z: 0.1
cal_floor: 0.1
cal_ceil: 5.0
cal_speed: 1.0
cal_move_speed: 10.0
scan_sweep_angle: 360

[temperature_sensor Cartographer_MCU]
sensor_type:   temperature_mcu
sensor_mcu:       cartographer
min_temp:                    0
max_temp:                  105
"""

        # Bed mesh section for scan probe type
        bed_mesh_lines = f"""
[bed_mesh]
zero_reference_position: {x_mid}, {y_mid}    
speed: 200
horizontal_move_z: 5
mesh_min: 35, 6
mesh_max: {x_mesh_max}, {y_mesh_max}
probe_count: 30, 30
algorithm: bicubic
"""

        # Insert the cartographer and bed mesh config lines
        insert_index = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("[include"):
                insert_index = i + 1

        lines.insert(insert_index, cartographer_config_lines)
        lines.insert(insert_index + 1, bed_mesh_lines)

        # Adding [adxl345] and [resonance_tester] sections for scan probe type
        adxl345_lines = f"""
[adxl345]
cs_pin: cartographer:PA3
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

        print(f"[cartographer] section added to printer.cfg successfully.")
    else:
        print("No updates made: Configuration already exists.")
# Function to update the [stepper_z] section
def update_stepper_z():
    all_cfg_files = [config_file_path] + process_includes(config_file_path)
    
    for file_path in all_cfg_files:
        #print(f"Processing file: {file_path}")
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
                print("Found [stepper_z] section.")  # Debugging output
            elif inside_stepper_z and stripped_line == "":
                # End of [stepper_z] section
                inside_stepper_z = False
                print("Exiting [stepper_z] section.")  # Debugging output
                # Add new lines if they haven't been added
                if not endstop_pin_updated:
                    updated_lines.append("endstop_pin: probe:z_virtual_endstop # uses cartographer as virtual endstop\n")
                    endstop_pin_updated = True
                    print("Added endstop_pin line.")  # Debugging output
                if not homing_retract_updated:
                    updated_lines.append("homing_retract_dist: 0 # cartographer needs this to be set to 0\n")
                    homing_retract_updated = True
                    print("Added homing_retract_dist line.")  # Debugging output
                updated_lines.append("")  # Blank line for separation
            else:
                if inside_stepper_z:
                    # Check for existing lines to update
                    if "endstop_pin:" in stripped_line and not endstop_pin_updated:
                        updated_lines.append("endstop_pin: probe:z_virtual_endstop # uses cartographer as virtual endstop\n")
                        endstop_pin_updated = True
                        print("Updated endstop_pin line.")  # Debugging output
                    elif "homing_retract_dist:" in stripped_line and not homing_retract_updated:
                        updated_lines.append("homing_retract_dist: 0 # cartographer needs this to be set to 0\n")
                        homing_retract_updated = True
                        print("Updated homing_retract_dist line.")  # Debugging output
                    elif stripped_line.startswith("position_endstop:"):
                        # Check if it's already commented out
                        if not stripped_line.startswith("#"):
                            updated_lines.append("#" + stripped_line + "\n")  # Comment out the existing line
                            position_endstop_commented = True
                            print("Commented out position_endstop line.")  # Debugging output
                        else:
                            updated_lines.append(line)  # Keep the original line if it's already commented
                    else:
                        updated_lines.append(line)  # Always add the line if not in stepper_z
                else:
                    updated_lines.append(line)  # Always add the line if not in stepper_z
        # Write the updated lines back to the file if changes were made
        if stepper_z_found and (endstop_pin_updated or homing_retract_updated):
            with open(file_path, "w") as file:
                file.writelines(updated_lines)
            print(f"Updated [stepper_z] section in {file_path}.")
            break
        else:
            if stepper_z_found:
                print(f"No updates made to [stepper_z] section in {file_path}.")
            #else:
                #print("[stepper_z] section not found in this file.")

    if not stepper_z_found:
        print("[stepper_z] section not found in any configuration files.")
def add_safe_z_home():
    # Only process the main printer.cfg file
    base_path = config_file_path
    
    # Get midpoints for home_xy_position
    x_mid, y_mid, x_mesh_max, y_mesh_max = get_position_max()

    # Find all relevant configuration files
    included_files = process_includes(base_path)
    included_files.append(base_path)  # Include the main file

    # Check for existing sections in all relevant configuration files
    homing_override_found = False
    safe_z_home_found = False

    for file in included_files:
        with open(file, "r") as f:
            lines = f.readlines()
            if any("[homing_override]" in line and not line.strip().startswith("#") for line in lines):
                homing_override_found = True
            if any("[safe_z_home]" in line and not line.strip().startswith("#") for line in lines):
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
                last_include_index = len(updated_lines)  # Update the last index for [include]

        # If there was at least one [include] section, add safe_z_home after it
        if last_include_index != -1:
            # Add safe_z_home_entry after the last [include] if it doesn't exist
            if not safe_z_home_found:
                updated_lines.insert(last_include_index, safe_z_home_entry)  # Add safe_z_home after the last [include]
                
                # Write back to the main printer.cfg file
                with open(base_path, "w") as f:
                    f.writelines(updated_lines)
                print(f"Added [safe_z_home] section after the last [include] section in {base_path}.")
            else:
                print("[safe_z_home] section already exists (commented or active).")
        else:
            print("[safe_z_home] section was not added because no [include] sections were found.")
    else:
        print("[homing_override] section exists; [safe_z_home] not added.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Install probe configuration in printer.cfg')
    parser.add_argument('--mode', choices=['scan', 'touch'], required=True,
                        help='Mode to install configuration for (scan or touch)')
    args = parser.parse_args()

    try:
        add_probe_config(args.mode)
        update_stepper_z()
        add_safe_z_home()
    except Exception as e:
        print(f"An error occurred: {e}")
