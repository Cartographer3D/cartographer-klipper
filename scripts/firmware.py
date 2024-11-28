import os

CONFIG_DIR: str = os.path.expanduser("~/printer_data/config")
KLIPPER_DIR: str = os.path.expanduser("~/klipper")
KATAPULT_DIR: str = os.path.expanduser("~/katapult")

DEBUG = True
FLASHER_VERSION: str = "0.0.1"


class Color(str):
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"

    def colored_text(self, text: str, color: str) -> str:
        return f"{color}{text}{self.RESET}"


class Menu:
    def __init__(self, title: str, menu_items: dict):
        self.color = Color()
        self.title = title
        self.menu_items = menu_items

    def display(self):
        while True:
            # Print menu header
            print("=" * 40)
            print(self.color.colored_text(self.title, self.color.RED))
            print("=" * 40)

            # Print menu items
            for key, (description, _) in self.menu_items.items():
                print(f"{key}. {description}")
            print("0. Exit")
            print("=" * 40)

            # Get user input
            try:
                choice = int(input("Select an option: ").strip())
            except ValueError:
                print(f"{Color.RED}Invalid input. Please enter a number.{Color.RESET}")
                continue

            # Handle exit
            if choice == 0:
                print("Exiting...")
                break

            # Call the corresponding function
            if choice in self.menu_items:
                _, function = self.menu_items[choice]
                print(
                    f"{Color.GREEN}You selected: {self.menu_items[choice][0]}{Color.RESET}\n"
                )
                function()  # Call the associated function
            else:
                print(f"{Color.RED}Invalid choice. Please try again.{Color.RESET}")


class Firmware:
    def __init__(self) -> None:
        self.color = Color()

    def error_msg(self, message: str) -> None:
        if message is not None and DEBUG:
            print(self.color.colored_text("Error:", Color.RED), message)

        return

    def success_msg(self, message: str) -> None:
        if message is not None and DEBUG:
            print(self.color.colored_text("Success:", self.color.GREEN), message)
        return

    def page(self, title: str) -> None:
        if title is not None and DEBUG:
            print(self.color.colored_text("Step:", self.color.MAGENTA), title)
        return

    def step_title(self, title: str) -> None:
        if title is not None and DEBUG:
            print(self.color.colored_text("Step:", self.color.YELLOW), title)
        return

    # Header for menus etc
    def header(self):
        print("=" * 100)
        print(
            " " * 35
            + self.color.colored_text("CARTOGRAPHER FIRMWARE FLASHER", self.color.CYAN)
        )
        print("=" * 100)

    # find can uuid from klippy.log
    def find_can_uuid(self) -> None:
        self.step_title("Finding CAN Device UUID")

    # Check status of UUID
    def get_can_status(self, uuid: str) -> None:
        self.step_title("Checking CAN Device Status")
        if not os.path.exists(KLIPPER_DIR):
            return self.error_msg(f"Directory '{KLIPPER_DIR}' does not exist")
        if uuid is None:
            return

    # find correct usb device for flashing
    def get_usb_device_id(self):
        self.step_title("Finding USB Device")

    # check if there is a device in DFU mode
    def is_dfu(self):
        self.step_title("Finding DFU Device")

    # Create main menu
    def main_menu(self):
        menu_items = {
            1: ("Option 1", self.method_menu),
            2: ("Option 2", self.firmware_menu),
        }

        menu = Menu("Main Menu", menu_items)
        menu.display()

    # Show what available flash methods there are
    def method_menu(self):
        self.page("Available Flashing Methods")

    # Show a list of available firmware
    def firmware_menu(self):
        self.page("Firmware Menu")

    # Confirm the user wants to flash the correct device & file
    def confirm(self):
        self.page("Confirm Flash")

    # Begin flashing procedure
    def flash(self):
        self.page("Flashing..")

    # If flash was a success
    def flash_success(self): ...
    # If flash failed
    def flash_fail(self): ...
    # Show what to do next screen
    def finished(self): ...


if __name__ == "__main__":
    fw = Firmware()
    fw.header()
    fw.main_menu()
