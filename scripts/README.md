
# Cartographer Setup Script v0.0.1 (WIP)

A Python script for installation of neccasary options into klipper config for cartographer (scanner) probe.

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

