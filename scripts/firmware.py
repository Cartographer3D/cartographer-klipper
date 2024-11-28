from enum import StrEnum  # type: ignore
import os

CONFIG_DIR: str = os.path.expanduser("~/printer_data/config")
KLIPPER_DIR: str = os.path.expanduser("~/klipper")
KATAPULT_DIR: str = os.path.expanduser("~/katapult")

DEBUG = True
FLASHER_VERSION: str = "0.0.1"


def clear_console():
    # For Windows
    if os.name == "nt":
        os.system("cls")
    # For MacOS and Linux (os.name is 'posix')
    else:
        os.system("clear")


def colored_text(text: str, color: str) -> str:
    return f"{color}{text}{Color.RESET}"


def error_msg(message: str) -> None:
    if message is not None and DEBUG:
        print(colored_text("Error:", Color.RED), message)
    return


def success_msg(message: str) -> None:
    if message is not None and DEBUG:
        print(colored_text("Success:", Color.GREEN), message)
    return


class Color(StrEnum):
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"

    def __str__(self) -> str:
        return super().__str__()


class Menu:
    class MenuItem:
        def __init__(self, description: str, action: callable):
            """
            Initialize a menu item with a description and action.

            Args:
                description (str): The description of the menu item.
                action (callable): The function to execute for this menu item.
            """
            self.description = description
            self.action = action

    def __init__(self, title: str, menu_items: dict[int, MenuItem]):
        self.title = title
        self.menu_items = menu_items

    def display(self):
        # Print menu header
        print("=" * 40)
        print(colored_text(self.title.center(40), Color.MAGENTA))
        print("=" * 40)

        # Print menu items
        for key, menu_item in self.menu_items.items():
            if key != 0:
                print(f"{key}. {menu_item.description}")
        print(colored_text("0. Exit", Color.RED))
        print("=" * 40)

        # Get user input
        try:
            choice = int(
                input(colored_text("Select an option: ", Color.YELLOW).strip())
            )
        except ValueError:
            print("Invalid input. Please enter a number.")
            return

        # Handle exit
        if choice == 0:
            print("Exiting...")
            return

        # Call the corresponding function
        if choice in self.menu_items:
            menu_item = self.menu_items[choice]
            menu_item.action()  # Call the action associated with the menu item
        else:
            print("Invalid choice. Please try again.")


class Firmware:
    def page(self, title: str) -> None:
        if title is not None and DEBUG:
            print(colored_text("Step:", Color.MAGENTA), title)
        return

    def step_title(self, title: str) -> None:
        if title is not None and DEBUG:
            print(colored_text(title, Color.YELLOW))
        return

    # Header for menus etc
    def header(self):
        clear_console()
        print("=" * 100)
        print(" " * 35 + colored_text("CARTOGRAPHER FIRMWARE FLASHER", Color.CYAN))
        print("=" * 100)

    # find can uuid from klippy.log
    def find_can_uuid(self) -> None:
        self.header()
        self.step_title("Finding CAN Device UUID")

    # Check status of UUID
    def get_can_status(self, uuid: str) -> None:
        self.header()
        self.step_title("Checking CAN Device Status")
        if not os.path.exists(KLIPPER_DIR):
            return error_msg(f"Directory '{KLIPPER_DIR}' does not exist")
        if uuid is None:
            return

    # find correct usb device for flashing
    def get_usb_device_id(self):
        self.header()
        self.step_title("Finding USB Device")

    # check if there is a device in DFU mode
    def is_dfu(self):
        self.header()
        self.step_title("Finding DFU Device")

    # Create main menu
    def main_menu(self):
        self.header()
        menu_items = {
            1: Menu.MenuItem("Katapult - CAN", self.can_menu),
            2: Menu.MenuItem("Katapult - USB", self.usb_menu),
            3: Menu.MenuItem("DFU", self.dfu_menu),
        }

        # Create and display the menu
        menu = Menu("Main Menu", menu_items)
        menu.display()

    # Show what available flash methods there are
    def can_menu(self):
        self.header()
        self.step_title("Select a CAN device")

    def usb_menu(self):
        self.header()
        self.step_title("Select a USB device")

    def dfu_menu(self):
        self.header()
        self.step_title("Select a DFU device")

    # Show a list of available firmware
    def firmware_menu(self):
        self.header()
        self.page("Firmware Menu")

    # Confirm the user wants to flash the correct device & file
    def confirm(self):
        self.header()
        self.page("Confirm Flash")

    # Begin flashing procedure
    def flash(self):
        self.header()
        self.page("Flashing..")

    # If flash was a success
    def flash_success(self):
        self.header()

    # If flash failed
    def flash_fail(self):
        self.header()

    # Show what to do next screen
    def finished(self):
        self.header()


if __name__ == "__main__":
    fw = Firmware()
    fw.main_menu()
