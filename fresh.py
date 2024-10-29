import os
import re
import glob

# Path to your printer.cfg file, with ~ expanded to the user's home directory
config_file_path = os.path.expanduser("~/printer_data/config/printer.cfg")

# Check if the main config file exists
if not os.path.exists(config_file_path):
    raise FileNotFoundError(f"The configuration file was not found at: {config_file_path}")

# Define the headers to comment out
headers_to_comment = ["scanner", "cartographer", "adxl345", "resonance_tester", "lis2dw", "bed_mesh"]  # Add other headers as needed

# Set the debug flag to True or False to enable/disable debug output
debug = False  # Set to False to disable debugging messages

def debug_print(message):
    """Print debug messages if debugging is enabled."""
    if debug:
        print(message)

# Function to comment out headers and their sections in a given file
def comment_headers_in_file(file_path):
    with open(file_path, "r") as file:
        lines = file.readlines()

    in_section = {header: False for header in headers_to_comment}
    updated_lines = []
    lines_commented = False

    # Create regex patterns for headers
    header_patterns = {header: re.compile(r"^\[" + re.escape(header) + r"\b") for header in headers_to_comment}
    section_header_pattern = re.compile(r"^\[.*\]")

    for line in lines:
        for header, pattern in header_patterns.items():
            if pattern.match(line):
                in_section[header] = True
                updated_lines.append("#" + line)  # Comment out the header line
                lines_commented = True
                break
        else:
            if any(in_section.values()):
                if section_header_pattern.match(line):
                    # A new section header is found; reset the section flags
                    for header in headers_to_comment:
                        in_section[header] = False  
                    updated_lines.append(line)  # Append the new section header without commenting
                else:
                    # Comment out non-header lines
                    if not line.lstrip().startswith("#") and line.strip() != "":
                        updated_lines.append("#" + line)
                        lines_commented = True
                    else:
                        updated_lines.append(line)
            else:
                updated_lines.append(line)

    if lines_commented:
        with open(file_path, "w") as file:
            file.writelines(updated_lines)
        debug_print(f"Updated {file_path}: Commented out lines in the specified sections.")
    else:
        debug_print(f"No lines were commented out in {file_path}.")

# Function to search for .cfg files in a directory and its subdirectories
def find_cfg_files(base_path):
    return [os.path.join(dirpath, f)
            for dirpath, _, files in os.walk(base_path)
            for f in files if f.endswith('.cfg')]

# Function to process includes
def process_includes(base_path):
    with open(base_path, "r") as file:
        lines = file.readlines()

    for line in lines:
        line = line.strip()
        if line.startswith("[include"):
            # Extract the pattern from the [include] lines
            include_pattern = line.split(" ", 1)[1].strip().strip("[]")

            # Construct the full path for the included files
            include_path = os.path.dirname(base_path)

            # Check for glob patterns in the includes
            if "*" in include_pattern:
                included_files = glob.glob(os.path.join(include_path, include_pattern))
            else:
                included_file = os.path.join(include_path, include_pattern)
                included_files = [included_file] if os.path.exists(included_file) else []  # Only include existing files

            # Find all .cfg files in the specified directory and subdirectories
            included_files += find_cfg_files(include_path)

            # Check if any files were found
            if included_files:
                debug_print(f"Processing included files: {included_files}")  # Debug line
                for included_file_path in set(included_files):  # Use set to avoid duplicates
                    if os.path.exists(included_file_path):  # Ensure the file exists before processing
                        comment_headers_in_file(included_file_path)
                    else:
                        debug_print(f"Skipping non-existent file: {included_file_path}")
            else:
                debug_print(f"No valid files found for include pattern: {include_pattern}")

# Function to delete lines starting with #*# and containing specified keywords
def delete_scanner_lines(file_path, keywords):
    with open(file_path, "r") as file:
        lines = file.readlines()

    updated_lines = []
    skip_lines = False

    for line in lines:
        # Check if the line starts with #*# and contains any of the keywords
        if line.startswith("#*#") and any(keyword in line for keyword in keywords):
            skip_lines = True  # Start skipping lines
            continue  # Skip this line
        
        # If we are skipping lines and we encounter a new header, stop skipping
        if skip_lines and re.match(r"^\[.*\]", line):
            skip_lines = False  # Stop skipping when a new header is found

            # Include this header in the updated lines
            updated_lines.append(line)
            continue  # Continue to process other lines

        # If not skipping, add the line to updated lines
        if not skip_lines:
            updated_lines.append(line)

    with open(file_path, "w") as file:
        file.writelines(updated_lines)
    debug_print(f"Updated {file_path}: Deleted scanner lines and related sections.")


# Define keywords to search for
keywords_to_delete = ["scanner", "cartographer"]  # Add other keywords as needed

# Process the main configuration file
process_includes(config_file_path)
comment_headers_in_file(config_file_path)
delete_scanner_lines(config_file_path, keywords_to_delete)

print("All previous instances of cartographer or scanner have been commented out or removed from your configuration files.")
print("Please visit https://docs.cartographer3d.com/cartographer-probe/installation-and-setup to continue installation")