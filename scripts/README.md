
# Firmware Flasher Script v0.0.1

A Python-based tool for managing and flashing firmware configurations for 3D printer setups. This script provides options to debug, select firmware versions, and handle configurations for CAN, USB, and DFU modes.

## Features

- **Interactive Menus:** Navigate through options with dynamic menus.
- **Debug Mode:** Enables detailed output for troubleshooting.
- **Firmware Selection:** Automatically retrieve and select firmware files based on device or user input.
- **Multi-mode Flashing:**
  - CAN: Supports flashing devices over CAN.
  - USB: Support for USB flashing (coming soon).
  - DFU: Support for DFU flashing (coming soon).
- **High-Temperature Firmware Support:** Search specifically for high-temperature configurations.
- **Katapult Support:** Includes integration with the Katapult tool for CAN device management.

## Prerequisites

- Python 3.8+ installed on your system.
- Access to required tools such as `curl` and `tar` for firmware handling.

## Usage

Run the script with various command-line arguments to perform tasks.

### Command-Line Arguments

| Argument        | Description                                                                     | Example Usage                       |
|-----------------|---------------------------------------------------------------------------------|-------------------------------------|
| `-b`, `--branch` | Specify the branch to retrieve firmware from (default: `master`).                | `python3 firmware.py -b dev`       |
| `-D`, `--debug`  | Enable debug mode for detailed output.                                         | `python3 firmware.py -D`           |
| `-t`, `--type`   | Enable Katapult flash mode.                                                    | `python3 firmware.py -t`           |
| `-H`, `--high-temp` | Search for high-temperature firmware (`HT` directories).                   | `python3 firmware.py -H`           |
| `-l`, `--latest` | Automatically flash the latest firmware without user selection.                | `python3 firmware.py -l`           |
| `-k`, `--kseries` | Enable support for Creality K-Series printers.                                | `python3 firmware.py -k`           |
| `-f`, `--flash`  | Specify the flashing mode (`CAN`, `USB`, or `DFU`).                            | `python3 firmware.py -f CAN`       |
| `-d`, `--device` | Specify a device UUID for flashing.                                            | `python3 firmware.py -d <UUID>`    |

### Examples

#### Flash Firmware via CAN
```bash
python3 firmware.py -f CAN
```

#### Enable Debug Mode
```bash
python3 firmware.py -d
```

#### Flash High-Temperature Firmware
```bash
python3 firmware.py -H -f CAN
```

#### Automatically Flash the Latest Firmware
```bash
python3 firmware.py -l -D <device>
```

## Menus

The script provides an interactive menu-based interface. Key menus include:

- **Main Menu:** Choose between CAN, USB, and DFU modes.
- **CAN Menu:** Options to find and flash CAN devices.
- **Firmware Menu:** List available firmware files and select one for flashing.
- **Confirmation Menu:** Confirm selected firmware and device before flashing.

## Debugging

Use the `-d` flag to enable debug mode, which provides detailed logs of operations.


# Cartographer Setup Script v0.0.1

A Python script for automatically setting up klipper 

It will create and add a folder and file, the include them in printer.cfg.

## Please make sure to check this before running as some options need to be self configured as follows

- [bed_mesh]
    min and max values
- [scanner]
    uuid or serial id
    X and Y offsets
    
    and possibly others, check them all

## Features
- **Debug Mode:** Enables detailed output for debugging purposes.
- **Probe Mode Selection:** Allows the user to choose between touch and scan probe modes.
- **Uninstall Functionality:** Removes existing probe configurations.

## Prerequisites
- Python 3.x installed on your system.
- Required Python libraries (if any, e.g., `argparse`).

## Usage
Run the script with the desired arguments to perform various tasks.

### Command-Line Arguments

| Argument        | Description                                 | Example Usage                    |
|-----------------|---------------------------------------------|-----------------------------------|
| `-d`, `--debug` | Enable debug mode for detailed output.      | `python3 script.py -d`           |
| `-m`, `--mode`  | Specify the probe mode: touch or scan.      | `python3 script.py -m touch`     |
| `-u`, `--uninstall` | Run uninstall function to remove probe configurations. | `python3 script.py -u` |

### Examples

#### Debug Mode
Enable detailed output for debugging:
```bash
python3 script.py -d
```

#### Select Probe Mode
Specify the mode as touch:
```bash
python3 script.py -m touch
```

Specify the mode as scan:
```bash
python3 script.py -m scan
```

#### Uninstall Probe Configurations
Run the uninstall function:
```bash
python3 script.py -u
```

## Contributing
Contributions are welcome! Feel free to fork the repository, make changes, and submit a pull request.