import os
import re
import subprocess
import argparse
import shutil
import tempfile
import fnmatch
import platform
import time

from enum import Enum  # type: ignore
from time import sleep
from typing import Optional, Tuple, Callable, NamedTuple, Dict, List, Union

HOME_PATH = os.path.expanduser("~")
CONFIG_DIR: str = os.path.expanduser("~/printer_data/config")
KLIPPY_LOG: str = os.path.expanduser("~/printer_data/logs/klippy.log")
KLIPPER_DIR: str = os.path.expanduser("~/klipper")
KATAPULT_DIR: str = os.path.expanduser("~/katapult")

FLASHER_VERSION: str = "0.0.1"

PAGE_WIDTH: int = 89  # Default global width

is_advanced: bool = False


class Color(Enum):
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


# Define a custom namespace class
class FirmwareNamespace(argparse.Namespace):
    branch: str = "master"
    debug: bool = False
    type: bool = False
    high_temp: bool = False
    all: bool = False
    kseries: bool = False
    device: Optional[str] = None
    flash: Optional[str] = None


class Version(NamedTuple):
    parts: Tuple[int, ...]

    @classmethod
    def from_string(cls, version: str) -> "Version":
        return cls(tuple(int(part) for part in version.split(".")))


class FirmwareFile(NamedTuple):
    subdirectory: str
    filename: str


class Utils:
    @staticmethod
    def make_terminal_bigger(width: int = 110, height: int = 40):
        system = platform.system()
        if system == "Windows":
            _ = os.system(f"mode con: cols={width} lines={height}")
        elif system in ["Linux", "Darwin"]:  # Darwin is macOS
            _ = os.system(f"printf '\\e[8;{height};{width}t'")
        else:
            print("Unsupported OS for resizing the terminal.")

    @staticmethod
    def clear_console():
        # For Windows
        if os.name == "nt":
            _ = os.system("cls")
        # For MacOS and Linux (os.name is 'posix')
        else:
            _ = os.system("clear")

    # Header for menus etc
    @staticmethod
    def header():
        Utils.clear_console()
        # Define the logo or ASCII art
        logo = """ 
        ____                  _                                            _               
/ ___|   __ _   _ __  | |_    ___     __ _   _ __    __ _   _ __   | |__     ___   _ __ 
| |      / _  | | '__| | __|  / _ \\   / _  | | '__|  / _  | | '_ \\  | '_ \\   / _ \\ | '__|
| |___  | (_| | | |    | |_  | (_) | | (_| | | |    | (_| | | |_) | | | | | |  __/ | |   
\\____|  \\__,_| |_|     \\__|  \\___/   \\__, | |_|     \\__,_| | .__/  |_| |_|  \\___| |_|   
            |___/                 |_|                          
        """
        # Calculate the width dynamically based on the longest line
        lines = logo.strip().split("\n")
        max_width = max(len(line) for line in lines)
        border = "=" * max_width

        # Print the header with borders
        print(border)
        for line in lines:
            print(Utils.colored_text(line.center(max_width), Color.GREEN))
        print(border)
        title = "CARTOGRAPHER FIRMWARE FLASHER"
        version = f" v{FLASHER_VERSION}"
        combined_title = Utils.colored_text(title, Color.CYAN) + Utils.colored_text(
            version, Color.RED
        )
        print(combined_title.center(105))

        # Display modes, centered
        Utils.display_modes(args)

        # Print the bottom border
        print("=" * max_width)

    @staticmethod
    def colored_text(text: str, color: Color) -> str:
        return f"{color.value}{text}{Color.RESET.value}"

    @staticmethod
    def error_msg(message: str) -> None:
        print(Utils.colored_text("Error:", Color.RED), message)
        _ = input(Utils.colored_text("\nPress Enter to continue...", Color.YELLOW))

    @staticmethod
    def success_msg(message: str) -> None:
        print(Utils.colored_text("Success:", Color.GREEN), message)
        _ = input(Utils.colored_text("\nPress Enter to continue...", Color.YELLOW))

    @staticmethod
    def page(title: str, width: int = PAGE_WIDTH) -> None:
        if len(title) > width:
            width = len(title) + 4  # Ensure width accommodates long titles with padding
        border = "=" * width
        print(border)
        print(Utils.colored_text(title.center(width), Color.CYAN))
        print(border)

    @staticmethod
    def display_modes(args: FirmwareNamespace) -> None:
        # Map conditions to mode strings
        mode_conditions = [
            (args.flash, lambda: f"{(args.flash or '').upper()} MODE"),
            (args.kseries, lambda: "K Series"),
            (args.high_temp, lambda: "HIGH TEMP"),
            (args.debug, lambda: "DEBUGGING"),
            (args.branch, lambda: f"BRANCH: {(args.branch or '').upper()}"),
            (args.type, lambda: "FLASH KATAPULT"),
            (args.all, lambda: "ALL FIRMWARE"),
            (is_advanced, lambda: "ADVANCED"),
        ]

        # Build modes list based on conditions
        modes = [
            generate_mode() for condition, generate_mode in mode_conditions if condition
        ]

        # Combine modes into a single string
        combined_modes = " | ".join(modes)
        Utils.show_mode(combined_modes)

    @staticmethod
    def show_mode(mode: str):
        # Center the mode string
        mode = mode.center(PAGE_WIDTH)
        print(Utils.colored_text(mode, Color.RED))


class Menu:
    title: str
    menu_items: Dict[int, Union["Menu.MenuItem", "Menu.Separator"]]

    class MenuItem:
        description: str
        action: Callable[[], None]

        def __init__(self, description: str, action: Callable[[], None]) -> None:
            self.description = description
            self.action = action

    class Separator:
        text: str
        """Represents a line separator in the menu."""

        def __init__(self, text: str = "") -> None:
            self.text = text

    def __init__(
        self, title: str, menu_items: Dict[int, Union["MenuItem", "Separator"]]
    ):
        self.title = title
        self.menu_items = menu_items

    def display(self) -> None:
        while True:
            # Determine and print the menu header
            width = max(
                PAGE_WIDTH, len(self.title) + 4
            )  # Ensure width accommodates long titles
            border = "=" * width
            print(border)
            print(Utils.colored_text(self.title.center(width).upper(), Color.MAGENTA))
            print(border)

            # Print menu items and separators
            indent = " "  # Adjust the number of spaces for indentation
            for key, menu_item in self.menu_items.items():
                if isinstance(menu_item, self.Separator):
                    print(
                        "-" * width + (f" {menu_item.text}" if menu_item.text else "")
                    )
                else:
                    item_color = Color.RED if key == 0 else None
                    print(
                        f"{indent}{key}.",
                        Utils.colored_text(menu_item.description, item_color)
                        if item_color
                        else menu_item.description,
                    )
            print(border)

            # Get user input
            choice = self.get()
            if choice == 0:
                print(Utils.colored_text("Exiting...", Color.CYAN))
                exit()

            # Validate and handle the choice
            if self.is_valid(choice):
                self.execute(choice)
                break
            else:
                self.invalid()

    def get(self) -> int:
        """Get and validate user input as an integer."""
        try:
            return int(
                input(Utils.colored_text(" Select an option: ", Color.YELLOW)).strip()
            )
        except ValueError:
            print(
                Utils.colored_text("Invalid input. Please enter a number.", Color.RED)
            )
            return -1  # Return -1 for invalid input

    def is_valid(self, choice: int) -> bool:
        """Check if the user's choice is valid."""
        return choice in self.menu_items and isinstance(
            self.menu_items[choice], self.MenuItem
        )

    def execute(self, choice: int) -> None:
        """Execute the action associated with a valid menu choice."""
        menu_item = self.menu_items[choice]
        if isinstance(menu_item, self.MenuItem):
            menu_item.action()  # Safe to call because type is now narrowed
        else:
            raise TypeError(f"Expected MenuItem, got {type(menu_item).__name__}")

    def invalid(self) -> None:
        """Display a message for an invalid choice."""
        Utils.header()
        print(Utils.colored_text("Invalid choice. Please try again.", Color.RED))


class Validator:
    """A utility class for common validation checks."""

    def __init__(self, firmware: "Firmware"):
        self.firmware: Firmware = (
            firmware  # Reference to the firmware object for navigation
        )

    def validate_device(self, device: str, type: str) -> bool:
        if type == "CAN":
            device_regex = r"^[a-f0-9]{12}$"
        elif type == "USB":
            device_regex = r".*Cartographer.*"
        else:
            device_regex = r"^[a-f0-9]{4}:[a-f0-9]{4}$"
        return bool(re.match(device_regex, device))

    def check_selected_firmware(self):
        if not self.firmware.selected_firmware:
            self._error_and_return("You have not selected a firmware file.")

    def check_selected_device(self):
        if not self.firmware.selected_device:
            self._error_and_return("You have not selected a device to flash.")

    def check_temp_directory(self):
        if self.firmware.dir_path is None:
            self._error_and_return("Error getting temporary directory path.")

    def _error_and_return(self, message: str):
        Utils.error_msg(message)
        _ = input(
            Utils.colored_text(
                "\nPress Enter to return to the main menu...", Color.YELLOW
            )
        )
        self.firmware.main_menu()


class Firmware:
    can: "Can"
    usb: "Usb"
    dfu: "Dfu"

    def __init__(
        self,
        branch: str = "master",
        debug: bool = False,
        ftype: bool = False,
        high_temp: bool = False,
        flash: Optional[str] = None,
        kseries: bool = False,
        all: bool = False,
        device: Optional[str] = None,
    ):
        self.selected_device: Optional[str] = None
        self.selected_firmware: Optional[str] = None
        self.dir_path: Optional[str] = None
        self.debug: bool = debug
        self.branch: str = branch
        self.ftype: bool = ftype

        self.high_temp: bool = high_temp
        self.flash: Optional[str] = flash
        self.kseries: bool = kseries
        self.all: bool = all
        self.device: Optional[str] = device
        self.can = Can(self, debug=self.debug, ftype=self.ftype)
        self.usb = Usb(self, debug=self.debug, ftype=self.ftype)
        self.dfu = Dfu(
            self, debug=self.debug, ftype=self.ftype
        )  # Pass Firmware instance to CAN
        self.validator: Validator = Validator(self)  # Initialize the Validator

    def set_device(self, device: str):
        self.selected_device = device

    def set_firmware(self, firmware: str):
        self.selected_firmware = firmware

    def get_device(self) -> Optional[str]:
        return self.selected_device  # None if not set, str if set

    def get_firmware(self) -> Optional[str]:
        return self.selected_firmware

    def handle_initialization(self):
        """
        Handle device initialization based on the flash type and device UUID.
        """
        handlers: Dict[str, Callable[[], None]] = {
            "CAN": self.can.menu,
            "USB": self.usb.menu,
            "DFU": self.dfu.menu,
        }

        if self.device and self.flash in handlers:
            # Validate the device
            if self.validator.validate_device(self.device, self.flash):
                self.set_device(self.device)

                # Handle --latest argument
                if not self.all:
                    self.firmware_menu(type=self.flash)

                # Call the appropriate menu directly from the handlers dictionary
                handlers[self.flash]()
        else:
            self.main_menu()

        # Fall back to the main menu if no valid condition is met
        self.main_menu()

    def find_firmware_files(
        self,
        base_dir: str,
        search_pattern: str = "*",
        exclude_pattern: Optional[Union[str, List[str]]] = None,
        high_temp: bool = False,
    ) -> List[FirmwareFile]:
        if not os.path.isdir(base_dir):
            print(f"Base directory does not exist: {base_dir}")
            return []

        firmware_files: List[FirmwareFile] = []

        # Traverse the directory structure
        for root, _, files in os.walk(base_dir):
            subdirectory = os.path.relpath(
                root, base_dir
            )  # Relative path of the subdirectory

            # Check high_temp condition
            if high_temp != ("HT" in subdirectory):
                continue

            for file in files:
                if not file.endswith(".bin"):  # Skip non-.bin files early
                    continue

                if not fnmatch.fnmatch(
                    file, search_pattern
                ):  # Skip files that don't match the inclusion pattern
                    continue

                # Handle exclusion patterns
                if exclude_pattern:
                    if isinstance(exclude_pattern, list):
                        # Skip files matching any pattern in the list
                        if any(
                            fnmatch.fnmatch(file, pattern)
                            for pattern in exclude_pattern
                        ):
                            continue
                    elif fnmatch.fnmatch(
                        file, exclude_pattern
                    ):  # Single exclude pattern
                        continue

                # Add valid firmware files to the list
                firmware_files.append(
                    FirmwareFile(subdirectory=subdirectory, filename=file)
                )

        return sorted(
            firmware_files, key=lambda f: f.subdirectory
        )  # Sort by subdirectory

    def select_latest(self, firmware_files: List[FirmwareFile], type: str):
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
            self.select_firmware(firmware_path, type)
            self.main_menu()
        else:
            print("No firmware files found in the latest subdirectory.")

    def set_advanced(self):
        global is_advanced
        if is_advanced:
            is_advanced = args.all = False
        else:
            is_advanced = args.all = True
        self.main_menu()

    def set_debugging(self):
        if self.debug:
            self.debug = args.debug = False
        else:
            self.debug = args.debug = True
        self.main_menu()

    def set_kseries(self):
        if self.kseries:
            self.kseries = args.kseries = False
            self.flash = args.flash = None
        else:
            self.kseries = args.kseries = True
            self.flash = args.flash = "USB"
        self.main_menu()

    def set_ftype(self):
        if self.ftype:
            self.ftype = args.type = False
        else:
            self.ftype = args.type = True
        self.main_menu()

    def set_high_temp(self):
        if self.high_temp:
            self.high_temp = args.high_temp = False
        else:
            self.high_temp = args.high_temp = True
        self.main_menu()

    def set_mode(self, mode: str):
        if mode:
            self.flash = args.flash = mode
        else:
            Utils.error_msg("You didnt specify a mode to use.")
        self.mode_menu()

    def set_branch(self, branch: str):
        if branch:
            self.branch = args.branch = branch
        else:
            Utils.error_msg("You didnt specify a branch to use.")
        self.branch_menu()

    def set_custom_branch(self):
        # Prompt user for a custom branch name or perform additional logic
        custom_branch = input("Enter the name of the custom branch: ").strip()
        if custom_branch:
            self.set_branch(custom_branch)
        else:
            print("No custom branch provided.")
            self.branch_menu()

    # Create main menu
    def main_menu(self) -> None:
        # Handle advanced mode and flash settings
        if is_advanced or self.flash == "DFU":
            self.all = True

        Utils.header()
        self.selected_device = None
        self.selected_firmware = None

        # Define base menu items
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
            1: Menu.MenuItem(
                "Katapult - CAN    "
                + Utils.colored_text("[For Flashing via CAN]", Color.YELLOW),
                self.can.menu,
            ),
            2: Menu.MenuItem(
                "Katapult - USB    "
                + Utils.colored_text("[For Flashing via USB]", Color.YELLOW),
                self.usb.menu,
            ),
            3: Menu.MenuItem(
                "DFU               "
                + Utils.colored_text("[For Flashing with DFU via USB]", Color.YELLOW),
                self.dfu.menu,
            ),
        }

        # Add advanced or basic options
        self.add_advanced_options(menu_items, is_advanced)

        # Add Exit option
        menu_items[len(menu_items) + 1] = Menu.Separator()
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("Main Menu", menu_items)
        menu.display()

    def add_advanced_options(
        self,
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]],
        is_advanced: bool,
    ) -> None:
        """Add advanced or basic options to the menu."""
        menu_items[len(menu_items) + 1] = Menu.Separator()

        # Advanced mode toggle
        mode_text = (
            "Enable Advanced Mode" if not is_advanced else "Disable Advanced Mode"
        )
        mode_color = Color.GREEN if not is_advanced else Color.RED
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text(mode_text, mode_color), self.set_advanced
        )

        if is_advanced:
            # Add advanced options
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                Utils.colored_text("Switch Flash Mode", Color.CYAN), self.mode_menu
            )
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                Utils.colored_text("Switch Branch", Color.CYAN), self.branch_menu
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()

            # Debugging toggle
            self.add_toggle_item(
                menu_items,
                "Debugging",
                self.debug,
                self.set_debugging,
            )

            # K Series firmware toggle
            self.add_toggle_item(
                menu_items,
                "Creality K Series Firmware",
                self.kseries,
                self.set_kseries,
            )

            # Katapult Bootloader toggle
            self.add_toggle_item(
                menu_items,
                "Katapult Bootloader Firmware",
                self.ftype,
                self.set_ftype,
            )

            # High Temp firmware toggle
            self.add_toggle_item(
                menu_items,
                "High Temp Firmware (HT Probes ONLY)",
                self.high_temp,
                self.set_high_temp,
            )

    def add_toggle_item(
        self,
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]],
        name: str,
        state: bool,
        action: Callable[[], None],
    ) -> None:
        """Helper function to add toggleable menu items."""
        text = f"Enable {name}" if not state else f"Disable {name}"
        color = Color.GREEN if not state else Color.RED
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text(text, color), action
        )

    def mode_menu(self):
        Utils.header()

        selected_text = Utils.colored_text("(selected)", Color.GREEN)

        # Define branch names and mark the selected branch
        modes = {"CAN": "CAN", "USB": "USB", "DFU": "DFU"}
        for key in modes:
            if key == self.flash:
                modes[key] += f" {selected_text}"

        # Prepare menu items
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {}

        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            modes["CAN"],
            lambda: self.set_mode("CAN"),
        )
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            modes["USB"],
            lambda: self.set_mode("USB"),
        )
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            modes["DFU"],
            lambda: self.set_mode("DFU"),
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text("Back to Main Menu", Color.CYAN),
            self.main_menu,
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add the "Exit" option last
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("Select a flashing mode", menu_items)
        menu.display()

    def branch_menu(self):
        def display_branch_table():
            # Table header
            print(f"{'Branch Name':<10} | {'Description'}")
            print("-" * 50)
            # Table rows
            print(f"{'Master':<10} | The most stable firmware version.")
            print(f"{'Beta':<10} | Firmware that is currently being tested.")
            print(f"{'Develop':<10} | Extremely experimental firmware.")
            print(f"{'Custom':<10} | Firmware from alternate branches.\n")

        print()
        Utils.header()
        display_branch_table()

        selected_text = Utils.colored_text("(selected)", Color.GREEN)

        # Define branch names and mark the selected branch
        branches = {
            "master": "Master",
            "beta": "Beta",
            "develop": "Develop",
        }
        for key in branches:
            if key == self.branch:
                branches[key] += f" {selected_text}"

        # Handle custom branch label
        if self.branch not in branches:
            custom_branch_label = f"{self.branch} {selected_text} - enter again?"
        else:
            custom_branch_label = "Custom Branch"

        # Prepare menu items
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {}

        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            branches["master"],
            lambda: self.set_branch("master"),
        )
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            branches["beta"],
            lambda: self.set_branch("beta"),
        )
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            branches["develop"],
            lambda: self.set_branch("develop"),
        )
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            custom_branch_label,
            self.set_custom_branch,
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text("Back to Main Menu", Color.CYAN),
            self.main_menu,
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add the "Exit" option last
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("Select a Branch to Flash From", menu_items)
        menu.display()

    def display_device(self):
        # Display selected device and firmware if available
        device: Optional[str] = self.get_device()
        if device:
            print(Utils.colored_text("Device Selected:", Color.MAGENTA), device)

    def display_firmware(self):
        firmware: Optional[str] = self.get_firmware()
        if firmware:
            print(
                Utils.colored_text("Firmware Selected:", Color.MAGENTA),
                firmware,
            )

    def display_firmware_menu(self, firmware_files: List[FirmwareFile], type: str):
        if firmware_files:
            # Define menu items for firmware files
            menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
                index: Menu.MenuItem(
                    f"{file.subdirectory}/{file.filename}",
                    lambda file=file: self.select_firmware(
                        os.path.join(file.subdirectory, file.filename), type
                    ),
                )
                for index, file in enumerate(firmware_files, start=1)
            }
            menu_items[len(menu_items) + 1] = Menu.Separator()
            # Add static options after firmware options
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Check Again", lambda: self.firmware_menu(type)
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem("Back", self.can.menu)
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                Utils.colored_text("Back to main menu", Color.CYAN), self.main_menu
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[0] = Menu.MenuItem("Exit", lambda: exit())  # Add Exit explicitly

            # Create and display the menu
            menu = Menu("Select Firmware", menu_items)
            menu.display()
        else:
            print("No firmware files found.")

    def select_firmware(self, firmware: str, type: str):
        self.set_firmware(firmware)
        menu_handlers: Dict[str, Callable[[], None]] = {
            "CAN": self.can.menu,
            "USB": self.usb.menu,
            "DFU": self.dfu.menu,
        }

        # Retrieve the appropriate handler and call it if valid
        handler = menu_handlers.get(type)
        if handler:
            handler()  # Call the appropriate menu method
        else:
            Utils.error_msg("You have not selected a valid firmware file.")

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
            exclude_pattern = None if bitrate else ["*USB*", "*K1*"]
        elif type == "USB":
            if getattr(self, "kseries", False):  # Check if kseries is True
                search_pattern = "*K1*USB*"
            else:
                search_pattern = "*USB*"
                exclude_pattern = ["*K1*"]
        else:
            search_pattern = "*"  # Default pattern for other types

        Utils.header()
        Utils.page(f"{type} Firmware Menu")

        # Initialize and retrieve firmware only when this method is called
        self.retrieve: RetrieveFirmware = RetrieveFirmware(
            self, branch=self.branch, debug=self.debug
        )
        self.retrieve.main()

        self.dir_path = self.retrieve.temp_dir_exists()  # Call the method

        if self.dir_path:
            # Start with the base path
            base_path = os.path.join(self.dir_path, "firmware/v2-v3/")

            if type != "DFU":
                if self.ftype:
                    base_path = os.path.join(base_path, "katapult-deployer")
                    search_pattern = "*katapult*"  # Include all files
                else:
                    base_path = os.path.join(base_path, "survey")
            else:
                self.all = True
                base_path = os.path.join(base_path, "combined-firmware")

            # Update self.dir_path only once
            self.dir_path = base_path
            firmware_files = self.find_firmware_files(
                self.dir_path, search_pattern, exclude_pattern, self.high_temp
            )
            if not self.all:
                self.select_latest(firmware_files, type)
            else:
                self.display_firmware_menu(firmware_files, type)

    # Confirm the user wants to flash the correct device & file
    def confirm(self, type: str):
        if not type:
            raise ValueError("type cannot be None or empty")

        Utils.header()
        Utils.page(f"Confirm {type} Flash")

        self.validator.check_selected_firmware()
        self.validator.check_selected_device()

        # Display selected firmware and device

        print(
            Utils.colored_text("Device to Flash:", Color.MAGENTA), self.selected_device
        )
        print(
            Utils.colored_text("Firmware to Flash:", Color.MAGENTA),
            self.selected_firmware,
        )

        # Dynamically get the appropriate menu method based on `type`

        # Map type to the appropriate object

        # Type mapping to dynamically resolve the target object

        type_mapping: Dict[str, Union[object, None]] = {
            "can": self.can,
            "usb": self.usb,
            "dfu": self.dfu,
        }

        # Get the target object based on the `type`
        target_object: Optional[object] = type_mapping.get(type.lower(), self)

        # Ensure target_object exists
        if not target_object:
            Utils.error_msg(
                f"Invalid type '{type}' provided; no corresponding object found."
            )
            return
        # Dynamically get the appropriate menu method from the target object
        menu_method_name: str = "menu"  # Construct the menu method name
        menu_method: Optional[Callable[[], None]] = getattr(
            target_object, menu_method_name, None
        )

        # Validate and call the menu method
        if menu_method is None or not callable(menu_method):
            Utils.error_msg(f"Menu for type '{type}' not found.")
            return
        # Ask for user confirmation
        print("\nAre these details correct?")
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
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
        Utils.header()
        Utils.page(f"Flashing via {type.upper()}..")
        self.validator.check_selected_firmware()
        self.validator.check_selected_device()
        self.validator.check_temp_directory()

        firmware_file = os.path.join(str(self.dir_path), str(self.selected_firmware))

        if not self.selected_device:
            Utils.error_msg("No device selected. Please select a device first.")
            return
        # Ensure the firmware file exists
        if not os.path.exists(firmware_file):
            Utils.error_msg(f"Firmware file not found: {firmware_file}")

        if type == "CAN":
            self.can.flash_device(firmware_file, self.selected_device)
        elif type == "USB":
            self.usb.flash_device(firmware_file, self.selected_device)
        elif type == "DFU":
            self.dfu.flash_device(firmware_file, self.selected_device)
        else:
            Utils.error_msg("You didnt select a valid flashing method")

    # If flash was a success
    def flash_success(self, result: str):
        Utils.header()
        Utils.page("Flashed Successfully")
        if self.debug:
            print(result)
        Utils.success_msg("Firmware flashed successfully to device!")
        # Clean the temporary directory
        if self.retrieve:
            self.retrieve.clean_temp_dir()
        self.main_menu()  # Return to the main menu or any other menu

    # If flash failed
    def flash_fail(self, message: str):
        Utils.header()
        Utils.page("Flash Error")
        # Clean the temporary directory
        if self.retrieve:
            self.retrieve.clean_temp_dir()
        Utils.error_msg(message)

    # Show what to do next screen
    def finished(self):
        Utils.header()


class Can:
    def __init__(self, firmware: Firmware, debug: bool = False, ftype: bool = False):
        self.firmware: Firmware = firmware
        self.validator: Validator = Validator(firmware)
        self.katapult_installer: Optional[KatapultInstaller] = None
        self.debug: bool = debug
        self.ftype: bool = ftype
        self.selected_device: Optional[str] = None
        self.selected_firmware: Optional[str] = None

    def katapult_check(self) -> bool:
        if not os.path.exists(KATAPULT_DIR):
            return False
        return True

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
            Utils.error_msg(f"Error retrieving bitrate: {e}")
            return None

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
            Utils.error_msg(f"Error checking CAN network: {e}")
            return False
        except Exception as e:
            # Handle unexpected errors
            Utils.error_msg(f"Unexpected error: {e}")
            return False

    def select_device(self, device: str):
        self.selected_device = device  # Save the selected device
        self.firmware.set_device(self.selected_device)
        self.menu()

    def enter_uuid(self):
        Utils.header()
        Utils.page("Enter UUID Manually")
        while True:
            user_input = input(
                "Enter your CAN UUID (or type 'back' to return): "
            ).strip()

            if user_input.lower() == "back":
                self.menu()  # Return to the CAN menu

            # Validate the UUID format (basic validation)
            if self.validator.validate_device(user_input, "CAN"):
                self.select_device(user_input)  # Save the UUID and return to CAN menu
                self.menu()
            else:
                Utils.error_msg(
                    "Invalid UUID format. Please try again., self.device_menu",
                )
                self.menu()

    def menu(self) -> None:
        Utils.header()
        self.firmware.display_device()
        self.firmware.display_firmware()
        self.selected_device = self.firmware.get_device()
        self.selected_firmware = self.firmware.get_firmware()

        # Base menu items
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
            1: Menu.MenuItem("Find Cartographer Device", self.device_menu),
            2: Menu.MenuItem(
                "Find CAN Firmware", lambda: self.firmware.firmware_menu(type="CAN")
            ),
        }

        # Dynamically add "Flash Selected Firmware" if conditions are met
        if self.selected_firmware and self.selected_device:
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Flash Selected Firmware", lambda: self.firmware.confirm(type="CAN")
            )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add "Back to main menu" after "Flash Selected Firmware"
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text("Back to main menu", Color.CYAN), self.firmware.main_menu
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add exit option explicitly at the end
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("What would you like to do?", menu_items)
        menu.display()

    def device_menu(self):
        Utils.header()

        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
            1: Menu.MenuItem("Check klippy.log", self.search_klippy),
            2: Menu.MenuItem("Enter UUID", self.enter_uuid),
            3: Menu.MenuItem("Query CAN Devices", self.query_devices),
            4: Menu.Separator(),  # Blank separator
            5: Menu.MenuItem(
                "Back",
                self.menu,
            ),
            6: Menu.MenuItem(
                Utils.colored_text("Back to main menu", Color.CYAN),
                self.firmware.main_menu,
            ),
            7: Menu.Separator(),  # Blank separator
            0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
        }

        # Create and display the menu
        menu = Menu("How would you like to find your CAN device?", menu_items)
        menu.display()

    def query_devices(self):
        Utils.header()
        Utils.page("Querying CAN devices..")
        detected_uuids: list[str] = []

        if not self.katapult_check():
            Utils.error_msg(
                "The Katapult directory doesn't exist or it is not installed.",
            )
            if self.katapult_installer is None:
                self.katapult_installer = KatapultInstaller(self.device_menu)

            # Define menu items
            menu_item: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
                1: Menu.MenuItem("Yes", self.katapult_installer.install),
                2: Menu.MenuItem(
                    Utils.colored_text("No, Back to CAN menu", Color.CYAN),
                    self.menu,
                ),
                3: Menu.Separator(),  # Blank separator
                0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
            }

            # Create and display the menu
            menu = Menu("Would you like to install Katapult?", menu_item)
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
                        Utils.error_msg("No CAN devices found.")
                        self.menu()
                else:
                    Utils.error_msg("Unexpected output format.")
                    self.menu()

            except subprocess.CalledProcessError as e:
                Utils.error_msg(f"Error querying CAN devices: {e}")
                self.menu()
            except Exception as e:
                Utils.error_msg(f"Unexpected error: {e}")
                self.menu()
            finally:
                # Define menu items, starting with UUID options
                menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {}
                for index, uuid in enumerate(detected_uuids, start=1):
                    menu_items[index] = Menu.MenuItem(
                        f"Select {uuid}", lambda uuid=uuid: self.select_device(uuid)
                    )
                menu_items[len(menu_items) + 1] = Menu.Separator()
                # Add static options after UUID options
                menu_items[len(menu_items) + 1] = Menu.MenuItem(
                    "Check Again", self.query_devices
                )
                menu_items[len(menu_items) + 1] = Menu.Separator()
                menu_items[len(menu_items) + 1] = Menu.MenuItem(
                    "Back", self.device_menu
                )
                menu_items[len(menu_items) + 1] = Menu.MenuItem(
                    Utils.colored_text("Back to main menu", Color.CYAN),
                    self.firmware.main_menu,
                )
                menu_items[len(menu_items) + 1] = Menu.Separator()
                # Add the Exit option explicitly
                menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

                # Create and display the menu
                menu = Menu("Options", menu_items)
                menu.display()

    # find can uuid from klippy.log
    def search_klippy(self) -> None:
        Utils.header()
        Utils.page("Finding CAN Device UUID via KLIPPY")

        try:
            if not self.check_can_network():
                Utils.error_msg(
                    "CAN network 'can0' is not active. Please ensure the CAN interface is configured.",
                )
                self.menu()

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
            menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {}
            for idx, uuid in enumerate(detected_uuids, start=1):
                if uuid in mcu_scanner_uuids:
                    menu_items[idx] = Menu.MenuItem(
                        f"Select {uuid} (MCU Scanner)",
                        lambda uuid=uuid: self.select_device(uuid),
                    )
                elif uuid in scanner_uuids:
                    menu_items[idx] = Menu.MenuItem(
                        f"Select {uuid} (Potential match)",
                        lambda uuid=uuid: self.select_device(uuid),
                    )
                else:
                    menu_items[idx] = Menu.MenuItem(
                        f"Select {uuid}", lambda uuid=uuid: self.select_device(uuid)
                    )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            # Add static options after UUID options
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Check Again", self.search_klippy
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem("Back", self.device_menu)
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                Utils.colored_text("Back to main menu", Color.CYAN),
                self.firmware.main_menu,
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            # Add the Exit option explicitly
            menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

            # Create and display the menu
            menu = Menu("Options", menu_items)
            menu.display()

        except FileNotFoundError:
            Utils.error_msg(
                f"KLIPPY log file not found at {KLIPPY_LOG}.",
            )
            self.menu()
        except Exception as e:
            Utils.error_msg(
                f"Unexpected error while processing KLIPPY log: {e}",
            )
            self.menu()

    def flash_device(self, firmware_file: str, device: str):
        try:
            self.validator.check_selected_device()
            self.validator.check_selected_firmware()
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

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Print stdout as it happens
            if process.stdout is not None:
                for line in process.stdout:
                    print(line.strip())

            # Wait for the process to complete
            _ = process.wait()

            # Check if the process completed successfully
            if process.returncode == 0:
                _ = input("Press enter to continue..")
                self.firmware.flash_success("Firmware flashed successfully.")
            else:
                stderr_output = (
                    process.stderr.read().strip()
                    if process.stderr is not None
                    else "No error details available."
                )
                _ = input("Press enter to continue..")
                self.firmware.flash_fail(f"Error flashing firmware: {stderr_output}")

        except subprocess.CalledProcessError as e:
            stderr_output = (
                e.stderr.strip() if e.stderr else "No error details available."
            )
            _ = input("Press enter to continue..")
            self.firmware.flash_fail(f"Error flashing firmware: {stderr_output}")
        except Exception as e:
            _ = input("Press enter to continue..")
            self.firmware.flash_fail(f"Unexpected error: {str(e)}")


class Usb:
    def __init__(self, firmware: Firmware, debug: bool = False, ftype: bool = False):
        self.firmware: Firmware = firmware
        self.validator: Validator = Validator(firmware)
        self.katapult_installer: Optional[KatapultInstaller] = None
        self.debug: bool = debug
        self.ftype: bool = ftype
        self.selected_device: Optional[str] = None
        self.selected_firmware: Optional[str] = None

    def katapult_check(self) -> bool:
        if not os.path.exists(KATAPULT_DIR):
            return False
        return True

    def select_device(self, device: str):
        self.selected_device = device  # Save the selected device globally
        self.firmware.set_device(self.selected_device)
        self.menu()

    def query_devices(self):
        Utils.header()
        Utils.page("Querying USB devices..")

        if not self.katapult_check():
            Utils.error_msg(
                "The Katapult directory doesn't exist or it is not installed.",
            )
            if self.katapult_installer is None:
                self.katapult_installer = KatapultInstaller(self.menu)

            # Define menu items
            menu_item: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
                1: Menu.MenuItem("Yes", self.katapult_installer.install),
                2: Menu.MenuItem(
                    Utils.colored_text("No, Back to USB menu", Color.CYAN),
                    self.menu,
                ),
                3: Menu.Separator(),  # Blank separator
                0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
            }

            # Create and display the menu
            menu = Menu("Would you like to install Katapult?", menu_item)
            menu.display()
        else:
            detected_devices: List[str] = []
            try:
                # List all devices in /dev/serial/by-id/
                base_path = "/dev/serial/by-id/"
                if not os.path.exists(base_path):
                    Utils.error_msg(f"Path '{base_path}' does not exist.")
                    self.menu()

                for device in os.listdir(base_path):
                    if "Cartographer" in device or "katapult" in device:
                        detected_devices.append(device)

                if not detected_devices:
                    Utils.error_msg(
                        "No devices containing 'Cartographer' or 'katapult' found."
                    )
                    self.menu()

                # Display the detected devices
                print("Available Cartographe/Katapult Devices:")
                print("=" * 40)
                for device in detected_devices:
                    print(device)
                print("=" * 40)

            except Exception as e:
                Utils.error_msg(f"Unexpected error while querying devices: {e}")
                self.menu()

            # Define menu items, starting with detected devices
            menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {}
            for index, device in enumerate(detected_devices, start=1):
                menu_items[index] = Menu.MenuItem(
                    f"Select {device}", lambda device=device: self.select_device(device)
                )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            # Add static options after the device options
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Check Again", self.query_devices
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem("Back", self.menu)
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                Utils.colored_text("Back to main menu", Color.CYAN),
                self.firmware.main_menu,
            )
            # Add the Exit option explicitly
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

            # Create and display the menu
            menu = Menu("Options", menu_items)
            menu.display()

    def menu(self) -> None:
        Utils.header()
        self.firmware.display_device()
        self.firmware.display_firmware()
        self.selected_device = self.firmware.get_device()
        self.selected_firmware = self.firmware.get_firmware()
        # Base menu items
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
            1: Menu.MenuItem("Find Cartographer Device", self.query_devices),
            2: Menu.MenuItem(
                "Find USB Firmware", lambda: self.firmware.firmware_menu(type="USB")
            ),
        }

        # Dynamically add "Flash Selected Firmware" if conditions are met
        if self.selected_firmware and self.selected_device:
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Flash Selected Firmware", lambda: self.firmware.confirm(type="USB")
            )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add "Back to main menu" after "Flash Selected Firmware"
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text("Back to main menu", Color.CYAN), self.firmware.main_menu
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add exit option explicitly at the end
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("What would you like to do?", menu_items)
        menu.display()

    def flash_device(self, firmware_file: str, device: str):
        try:
            # Validate selected device and firmware
            self.validator.check_selected_device()
            self.validator.check_selected_firmware()

            # Check if the device is already a Katapult device
            if "katapult" in device.lower():
                katapult_device = f"/dev/serial/by-id/{device}"
            else:
                # Validate that the device is a valid Cartographer device
                if not self.validator.validate_device(device, "USB"):
                    Utils.error_msg("Your device is not a valid Cartographer device.")
                    self.menu()

                # Prepend device path for Cartographer
                device = f"/dev/serial/by-id/{device}"

                # Enter bootloader for the device
                bootloader_cmd = [
                    os.path.expanduser("~/klippy-env/bin/python"),
                    "-c",
                    f"import flash_usb as u; u.enter_bootloader('{device}')",
                ]
                _ = subprocess.run(
                    bootloader_cmd,
                    text=True,
                    check=True,
                    cwd=os.path.expanduser("~/klipper/scripts"),
                )
                sleep(5)

                # Perform ls to find Katapult device
                base_path = "/dev/serial/by-id/"
                katapult_device = None
                if os.path.exists(base_path):
                    for item in os.listdir(base_path):
                        if "katapult" in item.lower():
                            katapult_device = f"{base_path}{item}"
                            break

                if not katapult_device:
                    Utils.error_msg(
                        "No Katapult device found after entering bootloader."
                    )
                    self.menu()
                    return

            # Prepare the flash command
            cmd: str = os.path.expanduser("~/katapult/scripts/flash_can.py")
            command = [
                "python3",
                cmd,
                "-f",
                firmware_file,  # Firmware file path
                "-d",
                katapult_device,  # Selected device UUID
            ]

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Print stdout as it happens
            if process.stdout is not None:
                for line in process.stdout:
                    print(line.strip())

            # Wait for the process to complete
            _ = process.wait()

            # Check if the process completed successfully
            if process.returncode == 0:
                _ = input("Press enter to continue..")
                self.firmware.flash_success("Firmware flashed successfully.")
            else:
                stderr_output = (
                    process.stderr.read().strip()
                    if process.stderr is not None
                    else "No error details available."
                )
                _ = input("Press enter to continue..")
                self.firmware.flash_fail(f"Error flashing firmware: {stderr_output}")

        except subprocess.CalledProcessError as e:
            stderr_output = (
                e.stderr.strip() if e.stderr else "No error details available."
            )
            _ = input("Press enter to continue..")
            self.firmware.flash_fail(f"Error flashing firmware: {stderr_output}")
        except Exception as e:
            _ = input("Press enter to continue..")
            self.firmware.flash_fail(f"Unexpected error: {str(e)}")


class Dfu:
    def __init__(self, firmware: Firmware, debug: bool = False, ftype: bool = False):
        self.firmware: Firmware = firmware
        self.validator: Validator = Validator(firmware)
        self.dfu_installer: Optional[DfuInstaller] = None
        self.debug: bool = debug
        self.ftype: bool = ftype
        self.selected_device: Optional[str] = None
        self.selected_firmware: Optional[str] = None

    def check_dfu_util(self) -> bool:
        if shutil.which("dfu-util"):
            return True
        else:
            print("dfu-util is not installed. Please install it and try again.")
            return False

    def dfu_loop(self) -> List[str]:
        start_time = time.time()
        timeout = 30  # Timeout in seconds

        detected_devices: List[str] = []

        try:
            while time.time() - start_time < timeout:
                # Run the `lsusb` command
                result = subprocess.run(
                    ["lsusb"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                lines = result.stdout.splitlines()

                # Parse all lines containing "DFU Mode"
                for line in lines:
                    if "DFU Mode" in line:
                        # Extract the device ID (the 6th field in `lsusb` output)
                        device_id: str = line.split()[
                            5
                        ]  # Assuming field 6 contains the ID
                        detected_devices.append(device_id)  # Add to the list
                        print(f"Detected DFU device: {device_id}")
                if detected_devices:
                    return detected_devices  # Exit both loops immediately

                print("No DFU devices found. Retrying in 1 second...")
                time.sleep(1)  # Wait 1 second before retrying

            print("No DFU devices found within the timeout period.")
        except KeyboardInterrupt:
            print("\nQuery canceled by user.")
            return []
        except Exception as e:
            print(f"Error while querying devices: {e}")
            return []

        # Return detected devices to avoid further processing if none found
        return detected_devices

    def query_devices(self):
        Utils.header()
        Utils.page("Querying DFU devices..")
        if not self.check_dfu_util():
            Utils.error_msg("DFU Util is not installed.")
            if self.dfu_installer is None:
                self.dfu_installer = DfuInstaller(self.menu)

            # Define menu items
            menu_item: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
                1: Menu.MenuItem("Yes", self.dfu_installer.install),
                2: Menu.MenuItem(
                    Utils.colored_text("No, Back to DFU menu", Color.CYAN),
                    self.menu,
                ),
                3: Menu.Separator(),  # Blank separator
                0: Menu.MenuItem("Exit", lambda: exit()),  # Add exit option explicitly
            }

            # Create and display the menu
            menu = Menu("Would you like to install DFU-Util?", menu_item)
            menu.display()
        else:
            print(
                f"You can now bridge the {Utils.colored_text('BOOT0', Color.YELLOW)} pins while plugging in Cartographer via USB at the same time.\n"
            )

            detected_devices: List[str] = self.dfu_loop()

            if detected_devices:
                Utils.success_msg("DFU Device Found")

            # Define menu items, starting with detected devices
            menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {}
            for index, device in enumerate(detected_devices, start=1):
                menu_items[index] = Menu.MenuItem(
                    f"Select {device}", lambda device=device: self.select_device(device)
                )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            # Add static options after the device options
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Check Again", self.query_devices
            )
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem("Back", self.menu)
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                Utils.colored_text("Back to main menu", Color.CYAN),
                self.firmware.main_menu,
            )
            # Add the Exit option explicitly
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

            # Create and display the menu
            menu = Menu("Options", menu_items)
            menu.display()

    def select_device(self, device: str):
        self.selected_device = device  # Save the selected device globally
        self.firmware.set_device(self.selected_device)
        self.menu()

    def menu(self) -> None:
        Utils.header()
        self.firmware.display_device()
        self.firmware.display_firmware()
        self.selected_device = self.firmware.get_device()
        self.selected_firmware = self.firmware.get_firmware()
        # Base menu items
        menu_items: Dict[int, Union[Menu.MenuItem, Menu.Separator]] = {
            1: Menu.MenuItem("Find Cartographer Device", self.query_devices),
            2: Menu.MenuItem(
                "Find DFU Firmware", lambda: self.firmware.firmware_menu(type="DFU")
            ),
        }

        # Dynamically add "Flash Selected Firmware" if conditions are met
        if self.selected_firmware and self.selected_device:
            menu_items[len(menu_items) + 1] = Menu.Separator()
            menu_items[len(menu_items) + 1] = Menu.MenuItem(
                "Flash Selected Firmware", lambda: self.firmware.confirm(type="DFU")
            )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add "Back to main menu" after "Flash Selected Firmware"
        menu_items[len(menu_items) + 1] = Menu.MenuItem(
            Utils.colored_text("Back to main menu", Color.CYAN), self.firmware.main_menu
        )
        menu_items[len(menu_items) + 1] = Menu.Separator()
        # Add exit option explicitly at the end
        menu_items[0] = Menu.MenuItem("Exit", lambda: exit())

        # Create and display the menu
        menu = Menu("What would you like to do?", menu_items)
        menu.display()

    def flash_device(self, firmware_file: str, device: str):
        try:
            # Validate selected device and firmware
            self.validator.check_selected_device()
            self.validator.check_selected_firmware()

            # Validate that the device is a valid Cartographer DFU device
            if not self.validator.validate_device(device, "DFU"):
                Utils.error_msg("Your device is not a valid Cartographer DFU device.")
                self.menu()

            # Prepare the dfu-util command
            command = [
                "sudo",
                "dfu-util",
                "--device",
                device,  # dfuID
                "-R",  # Reset after flashing
                "-a",
                "0",  # Alternate setting 0
                "-s",
                "0x08000000:leave",  # Address and leave DFU mode
                "-D",
                firmware_file,  # Firmware file path
            ]

            # Run the dfu-util command as a subprocess
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Print stdout as it happens
            if process.stdout is not None:
                for line in process.stdout:
                    print(line.strip())

            # Wait for the process to complete
            _ = process.wait()

            # Check stderr for known warnings to ignore
            stderr_output = (
                process.stderr.read().strip() if process.stderr is not None else ""
            )

            # Define warnings to ignore
            ignored_warnings = [
                "Invalid DFU suffix signature",
                "can't detach",
                "A valid DFU suffix",
            ]

            # Filter out ignored warnings
            filtered_stderr = "\n".join(
                line
                for line in stderr_output.splitlines()
                if not any(warning in line for warning in ignored_warnings)
            )

            # If returncode is 0 or all errors are ignored warnings, treat as success
            if process.returncode == 0 or (not filtered_stderr):
                _ = input("Press enter to continue..")
                self.firmware.flash_success("Firmware flashed successfully.")
            else:
                _ = input("Press enter to continue..")
                self.firmware.flash_fail(f"Error flashing firmware: {filtered_stderr}")

        except subprocess.CalledProcessError as e:
            stderr_output = (
                e.stderr.strip() if e.stderr else "No error details available."
            )
            _ = input("Press enter to continue..")
            self.firmware.flash_fail(f"Error flashing firmware: {stderr_output}")
        except Exception as e:
            _ = input("Press enter to continue..")
            self.firmware.flash_fail(f"Unexpected error: {str(e)}")


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
            return Utils.error_msg(f"Error downloading or extracting tarball: {e}")

    def find_extracted_dir(self):
        dirs = [
            os.path.join(self.temp_dir, d)
            for d in os.listdir(self.temp_dir)
            if os.path.isdir(os.path.join(self.temp_dir, d))
        ]
        if not dirs:
            return Utils.error_msg(
                "No directories found in the temporary directory after extraction."
            )
        self.extracted_dir = dirs[0]
        if self.debug:
            Utils.success_msg(f"Extracted directory: {self.extracted_dir}")

    def main(self):
        try:
            self.clean_temp_dir()
            self.download_and_extract()
            self.find_extracted_dir()
            if self.debug:
                Utils.success_msg(
                    f"Firmware from branch '{self.branch}' has been retrieved and prepared."
                )
        except Exception as e:
            Utils.error_msg(f"Failed to retrieve firmware: {e}")


class KatapultInstaller:
    def __init__(self, device_menu: Callable[[], None]) -> None:
        """
        Initialize the installer with a reference to the device menu callback.

        :param device_menu: A callable to return to the device menu.
        """
        self.device_menu: Callable[[], None] = device_menu

    def install(self) -> None:
        """
        Installs Katapult by cloning the repository to the specified directory.
        """
        try:
            # Check if Katapult is already installed
            if os.path.exists(KATAPULT_DIR):
                Utils.error_msg(
                    f"Katapult is already installed at {KATAPULT_DIR}.",
                )
                return

            # Command to clone the repository
            command = [
                "git",
                "clone",
                "https://github.com/Arksine/katapult.git",
                KATAPULT_DIR,
            ]

            print("Cloning the Katapult repository...")
            _ = subprocess.run(command, check=True, text=True)

            Utils.success_msg(
                f"Katapult has been successfully installed in {KATAPULT_DIR}."
            )

        except subprocess.CalledProcessError as e:
            Utils.error_msg(f"Error cloning Katapult repository: {e}")

        except Exception as e:
            Utils.error_msg(f"Unexpected error: {e}")

        finally:
            self.device_menu()


class DfuInstaller:
    def __init__(self, device_menu: Callable[[], None]) -> None:
        """
        Initialize the installer with a reference to the device menu callback.

        :param device_menu: A callable to return to the device menu.
        """
        self.device_menu: Callable[[], None] = device_menu

    def install(self) -> None:
        """
        Installs DFU Util
        """
        try:
            if shutil.which("apt"):
                Utils.success_msg(
                    "Detected apt package manager. Installing dfu-util..."
                )
                _ = subprocess.run(["sudo", "apt", "update"], check=True)
                _ = subprocess.run(
                    ["sudo", "apt", "install", "dfu-util", "-y"], check=True
                )
            elif shutil.which("yum"):
                Utils.success_msg(
                    "Detected yum package manager. Installing dfu-util..."
                )
                _ = subprocess.run(
                    ["sudo", "yum", "install", "dfu-util", "-y"], check=True
                )
            elif shutil.which("dnf"):
                Utils.success_msg(
                    "Detected dnf package manager. Installing dfu-util..."
                )
                _ = subprocess.run(
                    ["sudo", "dnf", "install", "dfu-util", "-y"], check=True
                )
            elif shutil.which("pacman"):
                Utils.success_msg(
                    "Detected pacman package manager. Installing dfu-util..."
                )
                _ = subprocess.run(
                    ["sudo", "pacman", "-S", "dfu-util", "--noconfirm"], check=True
                )
            else:
                Utils.error_msg(
                    "Package manager not supported. Please install dfu-util manually."
                )
                self.device_menu()

            Utils.success_msg("dfu-util installed successfully.")

        except subprocess.CalledProcessError as e:
            Utils.error_msg(f"Error occurred during installation: {e}")
            self.device_menu()
        except Exception as e:
            Utils.error_msg(f"Unexpected error: {e}")
            self.device_menu()
        finally:
            self.device_menu()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Firmware flashing script with -b to select branch"
    )
    _ = parser.add_argument(
        "-b", "--branch", help="Specify the branch name", default="master"
    )
    _ = parser.add_argument(
        "-D", "--debug", help="Enable debug output", action="store_true"
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
        "-a",
        "--all",
        help="Show all available firmware",
        action="store_true",
    )
    _ = parser.add_argument(
        "-k",
        "--kseries",
        help="Enable firmware for Creality K-Series printers",
        action="store_true",
    )
    _ = parser.add_argument("-d", "--device", help="Specify a device", default=None)
    _ = parser.add_argument(
        "-f",
        "--flash",
        help="Specify the flashing mode (CAN, USB, or DFU)",
        choices=["CAN", "USB", "DFU"],
        type=lambda s: s.upper(),
    )
    try:
        args = parser.parse_args(namespace=FirmwareNamespace())
        # Post-processing arguments
        if args.kseries:
            args.flash = "USB"  # Override the flash type to USB
        if args.type:
            args.all = True
        # Assign the argument to a variable
        branch = args.branch
        fw = Firmware(
            branch=args.branch,
            debug=args.debug,
            ftype=args.type,
            high_temp=args.high_temp,
            flash=args.flash,
            kseries=args.kseries,
            all=args.all,
            device=args.device,
        )
        ## TODO ##
        ## Adjust so users cannot be in certain modes together
        Utils.make_terminal_bigger()
        if args.all:
            if args.flash == "CAN":
                fw.can.menu()
            elif args.flash == "USB":
                fw.usb.menu()
            elif args.flash == "DFU":
                fw.dfu.menu()
            else:
                fw.main_menu()
        else:
            fw.handle_initialization()
    except KeyboardInterrupt:
        print("\nProcess interrupted by user. Exiting...")
        exit(0)
