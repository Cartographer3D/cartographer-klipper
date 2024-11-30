import os
import re
import subprocess
import argparse
import shutil
import tempfile
import fnmatch

from enum import Enum  # type: ignore
from typing import Optional, Tuple, Callable, NamedTuple, Dict, List, Union

HOME_PATH = os.path.expanduser("~")
CONFIG_DIR: str = os.path.expanduser("~/printer_data/config")
KLIPPY_LOG: str = os.path.expanduser("~/printer_data/logs/klippy.log")
KLIPPER_DIR: str = os.path.expanduser("~/klipper")
KATAPULT_DIR: str = os.path.expanduser("~/katapult")

FLASHER_VERSION: str = "0.0.1"


class Color(Enum):
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


# Define a custom namespace class
class FirmwareNamespace(argparse.Namespace):
    branch: str = "main"
    debug: bool = False
    type: bool = False
    high_temp: bool = False
    latest: bool = False
    kseries: bool = False
    device: Optional[str] = None
    flash: Optional[str] = None


class Version(NamedTuple):
    parts: Tuple[int, ...]

    @classmethod
    def from_string(cls, version: str) -> "Version":
        return cls(tuple(int(part) for part in version.split(".")))


def clear_console():
    # For Windows
    if os.name == "nt":
        _ = os.system("cls")
    # For MacOS and Linux (os.name is 'posix')
    else:
        _ = os.system("clear")


# Header for menus etc
def header():
    clear_console()
    # Print the top border
    print("=" * 60)
    # Center the title line
    title = "CARTOGRAPHER FIRMWARE FLASHER"
    version = f" v{FLASHER_VERSION}"
    combined_title = colored_text(title, Color.CYAN) + colored_text(version, Color.RED)
    print(combined_title.center(80))

    # Display modes, centered
    display_modes(args)

    # Print the bottom border
    print("=" * 60)


def colored_text(text: str, color: Color) -> str:
    return f"{color.value}{text}{Color.RESET.value}"


def error_msg(message: str, redirect: Optional[Callable[[], None]] = None) -> None:
    print(colored_text("Error:", Color.RED), message)
    _ = input(colored_text("\nPress Enter to continue...", Color.YELLOW))
    if redirect is None:
        fw.main_menu()  # Default to main menu
    else:
        if callable(redirect):  # Check if redirect is a callable
            redirect()


def success_msg(message: str, redirect: Optional[Callable[[], None]] = None) -> None:
    print(colored_text("Success:", Color.GREEN), message)
    _ = input(colored_text("\nPress Enter to continue...", Color.YELLOW))
    if redirect is None:
        fw.main_menu()  # Default to main menu
    else:
        if callable(redirect):  # Check if redirect is a callable
            redirect()


def page(title: str) -> None:
    print("=" * 40)
    print(colored_text(title.center(40), Color.CYAN))
    print("=" * 40)


def step_title(title: str) -> None:
    print(colored_text("Step: ", Color.YELLOW), title, "\n")


def display_modes(args: FirmwareNamespace) -> None:
    # Map conditions to mode strings
    mode_conditions = [
        (args.flash, lambda: f"{(args.flash or '').upper()} MODE"),
        (args.kseries, lambda: "K Series"),
        (args.high_temp, lambda: "HIGH TEMP"),
        (args.debug, lambda: "DEBUGGING"),
        (args.branch, lambda: f"BRANCH: {(args.branch or '').upper()}"),
        (args.type, lambda: "FLASH KATAPULT"),
        (args.latest, lambda: "FLASH LATEST"),
    ]

    # Build modes list based on conditions
    modes = [
        generate_mode() for condition, generate_mode in mode_conditions if condition
    ]

    # Combine modes into a single string
    combined_modes = " | ".join(modes)
    show_mode(combined_modes)


def show_mode(mode: str):
    # Center the mode string
    mode = mode.center(60)
    print(colored_text(mode, Color.RED))


class Menu:
    title: str
    menu_items: Dict[int, "Menu.MenuItem"]

    class MenuItem:
        description: str
        action: Callable[[], None]

        def __init__(self, description: str, action: Callable[[], None]) -> None:
            self.description = description
            self.action = action

    def __init__(self, title: str, menu_items: "dict[int, MenuItem]"):
        self.title = title
        self.menu_items = menu_items

    def display(self):
        # Print menu header
        print("=" * 40)
        print(colored_text(self.title.center(40), Color.MAGENTA))
        print("=" * 40)

        # Print menu items
        for key, menu_item in self.menu_items.items():
            if key == 0:
                print(f"{key}.", colored_text(menu_item.description, Color.RED))
            else:
                print(f"{key}. {menu_item.description}")
        print("=" * 40)

        # Get user input
        try:
            choice = int(
                input(colored_text("Select an option: ", Color.YELLOW)).strip()
            )
        except ValueError:
            print(colored_text("Invalid input. Please enter a number.", Color.RED))
            return

        # Handle exit explicitly for 0
        if choice == 0:
            print(colored_text("Exiting...", Color.CYAN))
            exit()

        # Call the corresponding function for valid choices
        if choice in self.menu_items:
            menu_item = self.menu_items[choice]
            menu_item.action()  # Call the action associated with the menu item
        else:
            print(colored_text("Invalid choice. Please try again.", Color.RED))


class Firmware:
    can: "CAN"

    def __init__(
        self,
        branch: str = "master",
        debug: bool = False,
        ftype: bool = False,
        high_temp: bool = False,
        flash: Optional[str] = None,
        kseries: bool = False,
        latest: bool = False,
        device: Optional[str] = None,
    ):
        self.selected_device: Optional[str] = None  # Initialize the selected UUID
        self.selected_firmware: Optional[str] = None
        self.dir_path: Optional[str] = None
        self.debug: bool = debug
        self.branch: str = branch
        self.ftype: bool = ftype

        self.high_temp: bool = high_temp
        self.flash: Optional[str] = flash
        self.kseries: bool = kseries
        self.latest: bool = latest
        self.device: Optional[str] = device
        self.can = CAN(
            self, debug=self.debug, ftype=self.ftype
        )  # Pass Firmware instance to CAN
        self.validator: Validator = Validator(self)  # Initialize the Validator

    def handle_initialization(self):
        # Handle specific device UUID
        if self.device:
            if self.can.validate_uuid(self.device):
                self.set_uuid(self.device)
                self.flash = "CAN"
                # Handle --latest argument
                if self.latest:
                    self.firmware_menu(
                        type=self.flash or "CAN"
                    )  # Default to "CAN" if no flash type
            self.can_menu()

        # Fall back to the main menu
        self.main_menu()

    def set_uuid(self, uuid: str) -> None:
        self.selected_device = uuid

    def get_uuid(self) -> Optional[str]:
        return self.selected_device  # None if not set, str if set

    # Create main menu
    def main_menu(self):
        header()
        menu_items = {
            1: Menu.MenuItem("Katapult - CAN", self.can_menu),
            2: Menu.MenuItem("Katapult - USB (Coming Soon)", self.usb_menu),
            3: Menu.MenuItem("DFU (Coming Soon)", self.dfu_menu),
            0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
        }

        # Create and display the menu
        menu = Menu("Main Menu", menu_items)
        menu.display()

    def can_menu(self):
        header()

        # Display selected UUID and firmware if available
        if self.get_uuid() is not None:
            print(colored_text("Device Selected:", Color.MAGENTA), self.get_uuid())

        if self.selected_firmware is not None:
            print(
                colored_text("Firmware Selected:", Color.MAGENTA),
                self.selected_firmware,
            )

        # Base menu items
        menu_items = {
            1: Menu.MenuItem("Find Cartographer Device", self.can_uuid_menu),
            2: Menu.MenuItem(
                "Find CAN Firmware", lambda: self.firmware_menu(type="CAN")
            ),
        }

        # Dynamically add "Flash Selected Firmware" if conditions are met
        if self.selected_firmware is not None and self.selected_device is not None:
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Flash Selected Firmware", lambda: self.confirm(type="CAN")
            )

        # Add "Back to main menu" after "Flash Selected Firmware"
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            colored_text("Back to main menu", Color.CYAN), self.main_menu
        )

        # Add exit option explicitly at the end
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("What would you like to do?", menu_items)
        menu.display()

    def can_uuid_menu(self):
        header()

        menu_items = {
            1: Menu.MenuItem("Check klippy.log", self.can.search_klippy),
            2: Menu.MenuItem("Enter UUID", self.can.enter_uuid),
            3: Menu.MenuItem("Query CAN Devices", self.can.query_can),
            4: Menu.MenuItem(
                "Back",
                self.can_menu,
            ),
            5: Menu.MenuItem(
                colored_text("Back to main menu", Color.CYAN), self.main_menu
            ),
            0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
        }

        # Create and display the menu
        menu = Menu("How would you like to find your CAN device?", menu_items)
        menu.display()

    def usb_menu(self):
        header()
        step_title("Select a USB device")
        error_msg("Error", self.dfu_menu)

    def dfu_menu(self):
        header()
        step_title("Select a DFU device")

    def find_firmware_files(
        self,
        base_dir: str,
        search_pattern: str = "*",
        exclude_pattern: Optional[Union[str, List[str]]] = None,
        high_temp: bool = False,
    ) -> List[Tuple[str, str]]:
        """
        Find firmware files in the given base directory.

        Args:
            base_dir (str): The base directory to search.
            search_pattern (str): Pattern to include files (default is '*').
            exclude_pattern (Optional[Union[str, List[str]]]): Pattern(s) to exclude files.
            high_temp (bool): Whether to include only high-temperature ('HT') directories.

        Returns:
            List[tuple[str, str]]: A sorted list of tuples containing subdirectory and file names.
        """
        if not os.path.isdir(base_dir):
            print(f"Base directory does not exist: {base_dir}")
            return []

        firmware_files: List[Tuple[str, str]] = []

        # Traverse the directory structure
        for root, _, files in os.walk(base_dir):
            subdirectory = os.path.relpath(
                root, base_dir
            )  # Relative path of the subdirectory

            if high_temp != ("HT" in subdirectory):
                continue

            for file in files:
                if file.endswith(".bin"):  # Only process .bin files
                    if fnmatch.fnmatch(file, search_pattern):  # Match inclusion pattern
                        # Handle exclude_pattern as a string or list
                        if exclude_pattern:
                            if isinstance(exclude_pattern, list):
                                # Skip files if they match any pattern in the list
                                if any(
                                    fnmatch.fnmatch(file, pattern)
                                    for pattern in exclude_pattern
                                ):
                                    continue
                            elif fnmatch.fnmatch(file, exclude_pattern):
                                continue
                        firmware_files.append((subdirectory, file))

        return sorted(firmware_files)  # Sort the results

    def select_latest(self, firmware_files: List[Tuple[str, str]]):
        if not firmware_files:
            print("No firmware files found.")
            return

        # Extract unique subdirectory names
        subdirectories = set(file[0] for file in firmware_files)
        if not subdirectories:
            print("No valid subdirectories found.")
            return

        latest_subdirectory = max(
            subdirectories,
            key=lambda d: Version.from_string(os.path.basename(d)),  # Parse version
        )
        # Filter firmware files in the latest subdirectory
        latest_firmware_files = [
            (subdirectory, file)
            for subdirectory, file in firmware_files
            if subdirectory == latest_subdirectory
        ]

        # Select the first firmware file in the latest subdirectory
        if latest_firmware_files:
            subdirectory, file = latest_firmware_files[0]
            firmware_path = os.path.join(subdirectory, file)  # Construct the full path
            self.select_firmware(firmware_path)
            self.main_menu()
        else:
            print("No firmware files found in the latest subdirectory.")

    def display_firmware_menu(self, firmware_files: List[Tuple[str, str]], type: str):
        if firmware_files:
            # Define menu items for firmware files
            menu_items = {
                index: Menu.MenuItem(
                    f"{subdirectory}/{file}",
                    lambda file=file, subdirectory=subdirectory: self.select_firmware(
                        os.path.join(subdirectory, file)
                    ),
                )
                for index, (subdirectory, file) in enumerate(firmware_files, start=1)
            }

            # Add static options after firmware options
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Check Again", lambda: self.firmware_menu(type)
            )
            menu_items[len(menu_items) + 1] = Menu.MenuItem("Back", self.can_menu)
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                colored_text("Back to main menu", Color.CYAN), self.main_menu
            )
            menu_items[0] = Menu.MenuItem("Exit", lambda: exit())  # Add Exit explicitly

            # Create and display the menu
            menu = Menu("Select Firmware", menu_items)
            menu.display()
        else:
            print("No firmware files found.")

    def select_firmware(self, firmware: str):
        self.selected_firmware = firmware  # Save the selected UUID globally
        self.can_menu()

    # Show a list of available firmware
    def firmware_menu(self, type: str):
        if not type:
            raise ValueError("type cannot be None or empty")
        # Get the bitrate from CAN interface
        bitrate = self.can.get_bitrate()

        # Determine search pattern and exclusion pattern
        exclude_pattern = None
        firmware_files = []  # Initialize firmware_files to avoid reference errors

        if type == "CAN":
            search_pattern = f"*{bitrate}*" if bitrate else "*"
            exclude_pattern = None if bitrate else ["*usb*", "*K1*"]
        elif type == "USB":
            if getattr(self, "kseries", False):  # Check if kseries is True
                search_pattern = "*K1*usb*"
            else:
                search_pattern = "*usb*"
                exclude_pattern = ["*K1*"]
        else:
            search_pattern = "*"  # Default pattern for other types

        header()
        page(f"{type} Firmware Menu")

        # Initialize and retrieve firmware only when this method is called
        self.retrieve: RetrieveFirmware = RetrieveFirmware(
            self, branch=self.branch, debug=self.debug
        )
        self.retrieve.main()

        self.dir_path = self.retrieve.temp_dir_exists()  # Call the method

        if self.dir_path:
            # Start with the base path
            base_path = os.path.join(self.dir_path, "firmware/v2-v3/")

            if self.ftype:
                base_path = os.path.join(base_path, "katapult-deployer")
                search_pattern = "*katapult*"  # Include all files
            elif type == "CAN":
                base_path = os.path.join(base_path, "survey")

            # Update self.dir_path only once
            self.dir_path = base_path
            firmware_files = self.find_firmware_files(
                self.dir_path, search_pattern, exclude_pattern, self.high_temp
            )
            if self.latest:
                self.select_latest(firmware_files)
            else:
                self.display_firmware_menu(firmware_files, type)

    # Confirm the user wants to flash the correct device & file
    def confirm(self, type: str):
        if not type:
            raise ValueError("type cannot be None or empty")

        header()
        page(f"Confirm {type} Flash")

        self.validator.check_selected_firmware()
        self.validator.check_selected_device()

        # Display selected firmware and device

        print(colored_text("Device to Flash:", Color.MAGENTA), self.selected_device)
        print(colored_text("Firmware to Flash:", Color.MAGENTA), self.selected_firmware)

        # Dynamically get the appropriate menu method based on `type`
        menu_method_name = (
            f"{type.lower()}_menu"  # Convert type to lowercase and append "_menu"
        )
        menu_method: Optional[Callable[[], None]] = getattr(
            self, menu_method_name, None
        )

        if menu_method is None or not callable(menu_method):
            error_msg(f"Menu for type '{type}' not found.")
            return

        # Ask for user confirmation
        print("\nAre these details correct?")
        menu_items = {
            1: Menu.MenuItem(
                "Yes, proceed to flash", lambda: self.firmware_flash(type)
            ),
            2: Menu.MenuItem(f"No, return to {type.upper()} menu", menu_method),
            0: Menu.MenuItem("Exit", lambda: exit()),  # Explicit exit option
        }

        # Display confirmation menu
        menu = Menu("Confirmation", menu_items)
        menu.display()

    # Begin flashing procedure
    def firmware_flash(self, type: str):
        header()
        page(f"Flashing via {type.upper()}..")
        self.validator.check_selected_firmware()
        self.validator.check_selected_device()
        self.validator.check_temp_directory()

        firmware_file = os.path.join(str(self.dir_path), str(self.selected_firmware))
        # Ensure the firmware file exists
        if not os.path.exists(firmware_file):
            error_msg(f"Firmware file not found: {firmware_file}")

        if type == "CAN":
            self.can.flash_can(firmware_file, self.selected_device)

    # If flash was a success
    def flash_success(self, result: str):
        header()
        page("Flashed Successfully")
        if self.debug:
            print(result)
        success_msg("Firmware flashed successfully to device!")
        # Clean the temporary directory
        if self.retrieve:
            self.retrieve.clean_temp_dir()
        self.main_menu()  # Return to the main menu or any other menu

    # If flash failed
    def flash_fail(self, message: str):
        header()
        page("Flash Error")
        # Clean the temporary directory
        if self.retrieve:
            self.retrieve.clean_temp_dir()
        error_msg(message)

    # Show what to do next screen
    def finished(self):
        header()


class CAN:
    def __init__(self, firmware: Firmware, debug: bool = False, ftype: bool = False):
        self.firmware: Firmware = firmware
        self.debug: bool = debug
        self.ftype: bool = ftype

    def get_bitrate(self, interface: str = "can0"):
        try:
            command = f"ip -s -d link show {interface}"
            result = os.popen(
                command
            ).read()  # Use subprocess for better control in production
            bitrate_match = re.search(r"bitrate\s(\d+)", result)
            if bitrate_match:
                return bitrate_match.group(1)
            else:
                return None
        except Exception as e:
            error_msg(f"Error retrieving bitrate: {e}", self.firmware.can_menu)
            return None

    def install_katapult(self):
        try:
            if os.path.exists(KATAPULT_DIR):
                error_msg(
                    f"Katapult is already installed at {KATAPULT_DIR}.",
                    self.firmware.can_uuid_menu,
                )
            command = [
                "git",
                "clone",
                "https://github.com/Arksine/katapult.git",
                KATAPULT_DIR,
            ]

            print("Cloning the Katapult repository...")
            _ = subprocess.run(command, check=True, text=True)

            success_msg(f"Katapult has been successfully installed in {KATAPULT_DIR}.")

        except subprocess.CalledProcessError as e:
            error_msg(
                f"Error cloning Katapult repository: {e}", self.firmware.can_uuid_menu
            )

        except Exception as e:
            error_msg(f"Unexpected error: {e}", self.firmware.can_uuid_menu)
        finally:
            _ = input("\nPress any key to return to the CAN menu...")
            self.firmware.can_uuid_menu()

    def katapult_check(self) -> bool:
        if not os.path.exists(KATAPULT_DIR):
            return False
        return True

    def check_can_network(self) -> bool:
        try:
            # Run the command
            command = ["ip", "-s", "-d", "link"]
            result = subprocess.run(command, text=True, capture_output=True, check=True)

            # Search for "can0" in the output
            if "can0" in result.stdout:
                return True
            else:
                return False

        except subprocess.CalledProcessError as e:
            # Handle the error gracefully if the command fails
            error_msg(f"Error checking CAN network: {e}", self.firmware.can_uuid_menu)
            return False
        except Exception as e:
            # Handle unexpected errors
            error_msg(f"Unexpected error: {e}", self.firmware.can_uuid_menu)
            return False

    # find can uuid from klippy.log
    def search_klippy(self) -> None:
        header()
        page("Finding CAN Device UUID via KLIPPY")

        try:
            if not self.katapult_check():
                error_msg(
                    "The Katapult directory doesn't exist or it is not installed.",
                    self.firmware.can_uuid_menu,
                )
                return

            if not self.check_can_network():
                error_msg(
                    "CAN network 'can0' is not active. Please ensure the CAN interface is configured.",
                    self.firmware.can_uuid_menu,
                )
                return

            mcu_scanner_uuids: list[str] = []  # UUIDs with [mcu scanner] above them
            scanner_uuids: list[str] = []  # UUIDs with [scanner] above them
            regular_uuids: list[str] = []  # UUIDs without either tag

            with open(KLIPPY_LOG, "r") as log_file:
                lines = log_file.readlines()

            # Parse the log to find UUIDs and their contexts
            for index, line in enumerate(lines):
                if "canbus_uuid =" in line:
                    # Extract the UUID
                    uuid = line.split("canbus_uuid =")[-1].strip()

                    # Check for [mcu scanner] or [scanner] in preceding lines
                    if index > 0 and "[mcu scanner]" in lines[index - 1]:
                        if uuid not in mcu_scanner_uuids:  # Avoid duplicates
                            mcu_scanner_uuids.append(uuid)
                    elif index > 0 and "[scanner]" in lines[index - 1]:
                        if uuid not in scanner_uuids:  # Avoid duplicates
                            scanner_uuids.append(uuid)
                    else:
                        if uuid not in regular_uuids:  # Avoid duplicates
                            regular_uuids.append(uuid)

            # Combine all categories: MCU scanner first, then scanner, then regular
            detected_uuids = mcu_scanner_uuids + scanner_uuids + regular_uuids

            # Prepare the menu
            menu_items: dict[int, Menu.MenuItem] = {}
            for idx, uuid in enumerate(detected_uuids, start=1):
                if uuid in mcu_scanner_uuids:
                    menu_items[idx] = Menu.MenuItem(
                        f"Select {uuid} (MCU Scanner)",
                        lambda uuid=uuid: self.select_uuid(uuid),
                    )
                elif uuid in scanner_uuids:
                    menu_items[idx] = Menu.MenuItem(
                        f"Select {uuid} (Potential match)",
                        lambda uuid=uuid: self.select_uuid(uuid),
                    )
                else:
                    menu_items[idx] = Menu.MenuItem(
                        f"Select {uuid}", lambda uuid=uuid: self.select_uuid(uuid)
                    )

            # Add static options after UUID options
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Check Again", self.search_klippy
            )
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Back", self.firmware.can_uuid_menu
            )
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                colored_text("Back to main menu", Color.CYAN),
                self.firmware.main_menu,
            )
            # Add the Exit option explicitly
            menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

            # Create and display the menu
            menu = Menu("Options", menu_items)
            menu.display()

        except FileNotFoundError:
            error_msg(
                f"KLIPPY log file not found at {KLIPPY_LOG}.",
                self.firmware.can_uuid_menu,
            )
        except Exception as e:
            error_msg(
                f"Unexpected error while processing KLIPPY log: {e}",
                self.firmware.can_uuid_menu,
            )

    def validate_uuid(self, uuid: str) -> bool:
        # Regex for a 12-character alphanumeric UUID (lowercase only)
        uuid_regex = r"^[a-f0-9]{12}$"
        return bool(re.match(uuid_regex, uuid))

    def enter_uuid(self):
        header()
        page("Enter UUID Manually")
        while True:
            user_input = input(
                "Enter your CAN UUID (or type 'back' to return): "
            ).strip()

            if user_input.lower() == "back":
                self.firmware.can_menu()  # Return to the CAN menu
                break

            # Validate the UUID format (basic validation)
            if self.validate_uuid(user_input):
                self.select_uuid(user_input)  # Save the UUID and return to CAN menu
                break
            else:
                error_msg(
                    "Invalid UUID format. Please try again., self.firmware.can_uuid_menu",
                    self.firmware.can_uuid_menu,
                )

    def query_can(self):
        header()
        page("Querying CAN devices..")

        detected_uuids: list[str] = []

        if not self.katapult_check():
            error_msg(
                "The Katapult directory doesn't exist or it is not installed.",
                self.firmware.can_uuid_menu,
            )
            # Define menu items
            menu_items = {
                1: Menu.MenuItem("Yes", self.install_katapult),
                2: Menu.MenuItem(
                    colored_text("No, Back to main menu", Color.CYAN),
                    self.firmware.main_menu,
                ),
                0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
            }

            # Create and display the menu
            menu = Menu("Would you like to install Katapult?", menu_items)
            menu.display()
        else:
            try:
                cmd = os.path.expanduser("~/katapult/scripts/flashtool.py")
                command = ["python3", cmd, "-i", "can0", "-q"]

                result = subprocess.run(
                    command, text=True, capture_output=True, check=True
                )

                # Parse and display the output
                output = result.stdout.strip()

                if "Query Complete" in output:
                    if "Detected UUID" in output:
                        print("Available CAN Devices:")
                        print("=" * 40)
                        # Extract and display each detected UUID
                        for line in output.splitlines():
                            if "Detected UUID" in line:
                                # Strip unnecessary parts and keep only the UUID
                                uuid = (
                                    line.split(",")[0]
                                    .replace("Detected UUID: ", "")
                                    .strip()
                                )
                                print(uuid)
                                detected_uuids.append(uuid)
                        print("=" * 40)
                    else:
                        error_msg("No CAN devices found.", self.firmware.can_uuid_menu)
                else:
                    error_msg("Unexpected output format.", self.firmware.can_uuid_menu)

            except subprocess.CalledProcessError as e:
                error_msg(
                    f"Error querying CAN devices: {e}", self.firmware.can_uuid_menu
                )
            except Exception as e:
                error_msg(f"Unexpected error: {e}", self.firmware.can_uuid_menu)
            finally:
                # Define menu items, starting with UUID options
                menu_items: dict[int, Menu.MenuItem] = {}
                for index, uuid in enumerate(detected_uuids, start=1):
                    menu_items[index] = Menu.MenuItem(
                        f"Select {uuid}", lambda uuid=uuid: self.select_uuid(uuid)
                    )

                # Add static options after UUID options
                menu_items[len(menu_items) + 1] = Menu.MenuItem(
                    "Check Again", self.query_can
                )
                menu_items[len(menu_items) + 1] = Menu.MenuItem(
                    "Back", self.firmware.can_uuid_menu
                )
                menu_items[len(menu_items) + 1] = Menu.MenuItem(
                    colored_text("Back to main menu", Color.CYAN),
                    self.firmware.main_menu,
                )
                # Add the Exit option explicitly
                menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

                # Create and display the menu
                menu = Menu("Options", menu_items)
                menu.display()

    def select_uuid(self, uuid: str):
        selected_device = uuid  # Save the selected UUID globally
        self.firmware.set_uuid(selected_device)
        self.firmware.can_menu()

    def retrieve_uuid(self) -> Optional[str]:
        return self.firmware.get_uuid()

    def flash_can(self, firmware_file: str, device: Optional[str]):
        try:
            if device is None:
                raise ValueError("Device UUID must not be None.")

            # Prepare the command to execute the flash script
            cmd: str = os.path.expanduser("~/katapult/scripts/flash_can.py")
            command = [
                "python3",
                cmd,
                "-i",
                "can0",  # CAN interface
                "-f",
                firmware_file,  # Firmware file path
                "-u",
                device,  # Selected device UUID
            ]

            # Execute the command
            result = subprocess.run(command, text=True, capture_output=True, check=True)

            # Output the results
            self.firmware.flash_success(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            # Handle errors during the command execution
            self.firmware.flash_fail(f"Error flashing firmware: {e}")


class USB:
    # find correct usb device for flashing
    def get_usb_device_id(self):
        header()
        step_title("Finding USB Device")


class DFU:
    # check if there is a device in DFU mode
    def is_dfu(self):
        header()
        step_title("Finding DFU Device")


class Validator:
    """A utility class for common validation checks."""

    def __init__(self, firmware: Firmware):
        self.firmware: Firmware = (
            firmware  # Reference to the firmware object for navigation
        )

    def check_selected_firmware(self):
        if self.firmware.selected_firmware is None:
            self._error_and_return("You have not selected a firmware file.")

    def check_selected_device(self):
        if self.firmware.selected_device is None:
            self._error_and_return("You have not selected a device to flash.")

    def check_temp_directory(self):
        if self.firmware.dir_path is None:
            self._error_and_return("Error getting temporary directory path.")

    def _error_and_return(self, message: str):
        error_msg(message)
        _ = input(
            colored_text("\nPress Enter to return to the main menu...", Color.YELLOW)
        )
        self.firmware.main_menu()


class RetrieveFirmware:
    def __init__(self, firmware: Firmware, branch: str = "master", debug: bool = False):
        self.firmware: Firmware = firmware
        self.branch: str = branch
        self.debug: bool = debug
        self.tarball_url: str = f"https://api.github.com/repos/Cartographer3D/cartographer-klipper/tarball/{self.branch}"
        self.temp_dir: str = tempfile.mkdtemp(prefix="cartographer-klipper_")
        self.extracted_dir: Optional[str] = None

    def temp_dir_exists(self) -> Optional[str]:
        if self.debug:
            print(f"Checking temporary directory: {self.temp_dir}")
        if os.path.exists(self.temp_dir):
            if self.debug:
                print(f"Directory exists: {self.temp_dir}")
            subdirs = [
                os.path.join(self.temp_dir, d)
                for d in os.listdir(self.temp_dir)
                if os.path.isdir(os.path.join(self.temp_dir, d))
            ]
            if self.debug:
                print(f"Subdirectories found: {subdirs}")
            if subdirs:
                return subdirs[0]
        if self.debug:
            print("No subdirectories found.")
        return None

    def clean_temp_dir(self):
        if os.path.exists(self.temp_dir):
            if self.debug:
                print(f"Cleaning temporary directory: {self.temp_dir}")
            shutil.rmtree(self.temp_dir)
        os.makedirs(self.temp_dir, exist_ok=True)

    def download_and_extract(self):
        try:
            # Define the path for the downloaded tarball
            tarball_path = os.path.join(self.temp_dir, "firmware.tar.gz")

            print("Downloading tarball...")
            # Use curl to save the tarball to a file
            with open(os.devnull, "w") as devnull:
                curl_command = [
                    "curl",
                    "-L",
                    self.tarball_url,
                    "--output",
                    tarball_path,
                ]
                _ = subprocess.run(
                    curl_command,
                    stdout=devnull if not self.debug else None,
                    stderr=devnull,
                    check=True,
                )

            print("Extracting tarball...")
            # Extract the tarball into the temporary directory
            with open(os.devnull, "w") as devnull:
                tar_command = ["tar", "-xz", "-C", self.temp_dir, "-f", tarball_path]
                _ = subprocess.run(
                    tar_command,
                    stdout=devnull if not self.debug else None,
                    stderr=devnull,
                    check=True,
                )

        except subprocess.CalledProcessError as e:
            return error_msg(f"Error downloading or extracting tarball: {e}")

    def find_extracted_dir(self):
        dirs = [
            os.path.join(self.temp_dir, d)
            for d in os.listdir(self.temp_dir)
            if os.path.isdir(os.path.join(self.temp_dir, d))
        ]
        if not dirs:
            return error_msg(
                "No directories found in the temporary directory after extraction."
            )
        self.extracted_dir = dirs[0]
        if self.debug:
            success_msg(f"Extracted directory: {self.extracted_dir}")

    def main(self):
        try:
            self.clean_temp_dir()
            self.download_and_extract()
            self.find_extracted_dir()
            if self.debug:
                success_msg(
                    f"Firmware from branch '{self.branch}' has been retrieved and prepared."
                )
        except Exception as e:
            error_msg(f"Failed to retrieve firmware: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Firmware flashing script with -b to select branch"
    )
    _ = parser.add_argument(
        "-b", "--branch", help="Specify the branch name", default="main"
    )
    _ = parser.add_argument(
        "-d", "--debug", help="Enable debug output", action="store_true"
    )
    _ = parser.add_argument(
        "-t", "--type", help="Enable katapult flash", action="store_true"
    )
    _ = parser.add_argument(
        "-H",
        "--high-temp",
        help="Search for high-temperature firmware (HT folders)",
        action="store_true",
    )
    _ = parser.add_argument(
        "-l",
        "--latest",
        help="Skip searching for firmware and flash latest",
        action="store_true",
    )
    _ = parser.add_argument(
        "-k",
        "--kseries",
        help="Enable firmware for Creality K-Series printers",
        action="store_true",
    )
    _ = parser.add_argument("-D", "--device", help="Specify a device", default=None)
    _ = parser.add_argument(
        "-f",
        "--flash",
        help="Specify the flashing mode (CAN, USB, or DFU)",
        choices=["CAN", "USB", "DFU"],
        type=lambda s: s.upper(),
    )

    args = parser.parse_args(namespace=FirmwareNamespace())
    # Post-processing arguments
    if args.kseries:
        args.flash = "USB"  # Override the flash type to USB

    # Assign the argument to a variable
    branch = args.branch
    fw = Firmware(
        branch=args.branch,
        debug=args.debug,
        ftype=args.type,
        high_temp=args.high_temp,
        flash=args.flash,
        kseries=args.kseries,
        latest=args.latest,
        device=args.device,
    )
    if not args.latest:
        if args.flash == "CAN":
            fw.can_menu()
        elif args.flash == "USB":
            fw.usb_menu()
        elif args.flash == "DFU":
            fw.dfu_menu()
        else:
            fw.main_menu()
    else:
        fw.handle_initialization()
