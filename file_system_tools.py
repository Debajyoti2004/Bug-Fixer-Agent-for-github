
import os

def read_file(file_path: str) -> str:
    if not os.path.exists(file_path):
        return f"Error: File '{file_path}' not found."
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(file_path: str, content: str) -> str:
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"File '{file_path}' written successfully."
    except Exception as e:
        return f"Error writing to file {file_path}: {e}, Content to be written on this file:{content}"

def list_files(directory: str = '.') -> str:
    try:
        files = os.listdir(directory)
        return "\n".join(files)
    except Exception as e:
        return f"Error listing files: {e}"