import os
import shutil
from pathlib import Path

def format_name(name):
    """Convert hyphenated names to spaced names with proper capitalization"""
    return ' '.join(word.capitalize() for word in name.replace('-', ' ').split())

def rename_folders(base_path):
    """Rename folders in the pins directory, replacing hyphens with spaces"""
    pins_dir = Path(base_path) / 'pins'
    
    if not pins_dir.exists():
        print(f"❌ Directory not found: {pins_dir}")
        return
    
    # First, process board folders
    for board_folder in pins_dir.iterdir():
        if not board_folder.is_dir():
            continue
            
        # Format the new board name
        new_board_name = format_name(board_folder.name)
        if new_board_name != board_folder.name:
            new_board_path = board_folder.parent / new_board_name
            print(f"Renaming board folder: {board_folder.name} → {new_board_name}")
            shutil.move(str(board_folder), str(new_board_path))
            board_folder = new_board_path
        
        # Then process section folders within each board
        for section_folder in board_folder.iterdir():
            if not section_folder.is_dir():
                continue
                
            # Format the new section name
            new_section_name = format_name(section_folder.name)
            if new_section_name != section_folder.name:
                new_section_path = section_folder.parent / new_section_name
                print(f"  Renaming section folder: {section_folder.name} → {new_section_name}")
                shutil.move(str(section_folder), str(new_section_path))

if __name__ == "__main__":
    rename_folders('.')
    print("✅ Folder renaming complete!") 