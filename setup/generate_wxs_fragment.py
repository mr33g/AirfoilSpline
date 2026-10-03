import os
import uuid
import hashlib
import argparse
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Directories to exclude from the installer (don't install files from these)
BASE_EXCLUDED_DIRS = {
    'tests',
    'build',
    'dist',
    '.venv',
    'setup',        # Don't include the setup folder (contains MSI, build artifacts)
    '.git',         # Don't include git repository
    '.vscode',      # Don't include VS Code settings
    '__pycache__',  # Don't include Python cache (but we DO need to clean it up on uninstall)
    '.idea',        # Don't include JetBrains IDE settings
    '.claude',
    '.github',
    'res'
}

# Directories that may be created at runtime and need cleanup on uninstall
RUNTIME_CLEANUP_DIRS = {
    '__pycache__',  # Python bytecode cache - created at runtime
}

# File patterns to exclude
EXCLUDED_FILES = {
    '.gitignore',
    '.DS_Store',
    'Thumbs.db',
}

def make_id(prefix, path):
    """Creates a valid WiX ID, hashing it if it exceeds the 72-char limit."""
    safe_path = path.replace(os.sep, "_").replace(".", "_").replace("-", "_")
    full_id = f"{prefix}_{safe_path}"
    if len(full_id) <= 72:
        return full_id
    
    # Hash the path and append to prefix for a unique, short ID
    hash_str = hashlib.md5(path.encode()).hexdigest()[:16]
    return f"{prefix}_{hash_str}"

def should_exclude_dir(dirpath, source_dir, excluded_dirs):
    """Check if a directory should be excluded."""
    rel_path = os.path.relpath(dirpath, source_dir)
    parts = rel_path.split(os.sep)
    
    # Check if any part of the path is in excluded dirs
    for part in parts:
        if part in excluded_dirs:
            return True
    return False

def generate_wxs_fragment(source_dir, output_file, component_group_id, directory_id_root, exclude_lib=False):
    """
    Generates a WiX v4+ fragment (.wxs) for all files in a source directory.
    
    Args:
        source_dir: Source directory to scan
        output_file: Output .wxs file path
        component_group_id: WiX component group ID
        directory_id_root: Root directory ID
        exclude_lib: If True, exclude the 'lib' directory from the installer
    """
    # Calculate relative path from setup folder (where output_file is) to source_dir
    setup_dir = os.path.dirname(os.path.abspath(output_file))
    source_dir_abs = os.path.abspath(source_dir)
    try:
        source_dir_rel = os.path.relpath(source_dir_abs, setup_dir).replace(os.sep, '/')
        # Ensure we have at least "./" prefix if in same directory
        if not source_dir_rel.startswith('..') and not source_dir_rel.startswith('.'):
            source_dir_rel = f"./{source_dir_rel}"
    except ValueError:
        # On Windows, if drives differ, use absolute path
        source_dir_rel = source_dir_abs.replace(os.sep, '/')
    
    # Build excluded directories list
    excluded_dirs = BASE_EXCLUDED_DIRS.copy()
    if exclude_lib:
        excluded_dirs.add('lib')
    
    # Use the WiX v4+ namespace (include util if we need RemoveFolderEx)
    root = ET.Element("Wix", xmlns="http://wixtoolset.org/schemas/v4/wxs")
    fragment = ET.SubElement(root, "Fragment")
    
    # Track directories to avoid duplicates
    dir_map = {".": directory_id_root, "": directory_id_root}
    
    # Track __pycache__ directories that need cleanup (they're created at runtime)
    pycache_dirs = set()
    
    # 1. Define Directory Structure
    # We walk once to collect all directories (including __pycache__ for cleanup purposes)
    # Use a separate walk that doesn't skip __pycache__ to ensure we catch all of them
    for dirpath, dirnames, filenames in os.walk(source_dir):
        rel_path = os.path.relpath(dirpath, source_dir)
        
        # Check if this is a __pycache__ directory - we need to track these for cleanup
        if os.path.basename(dirpath) == '__pycache__':
            pycache_dirs.add(rel_path)
            pycache_id = make_id("DIR", rel_path)
            dir_map[rel_path] = pycache_id
            # Don't descend into __pycache__ directories (they shouldn't have nested ones)
            dirnames[:] = []
            continue
        
        # Skip fully excluded directories (but we've already handled __pycache__ above)
        if should_exclude_dir(dirpath, source_dir, excluded_dirs):
            continue
            
        # Prune excluded directories from walk (but still record __pycache__ paths above)
        original_dirnames = list(dirnames)
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        
        # Track __pycache__ subdirectories for cleanup
        for d in original_dirnames:
            if d == '__pycache__':
                pycache_rel = os.path.join(rel_path, d) if rel_path not in [".", ""] else d
                pycache_dirs.add(pycache_rel)
                pycache_id = make_id("DIR", pycache_rel)
                dir_map[pycache_rel] = pycache_id
            
        if rel_path in [".", ""]:
            continue
            
        dir_id = make_id("DIR", rel_path)
        dir_map[rel_path] = dir_id
    
    # 2. Components and Files
    comp_group = ET.SubElement(fragment, "ComponentGroup", Id=component_group_id)
    
    # Track directories that need RemoveFolder elements (to clean up on uninstall)
    dirs_needing_cleanup = set()
    
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(source_dir):
        # Skip excluded directories
        if should_exclude_dir(dirpath, source_dir, excluded_dirs):
            continue
            
        # Prune excluded directories from walk
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
            
        rel_path = os.path.relpath(dirpath, source_dir)
        dir_id = dir_map.get(rel_path, directory_id_root)
        
        # Track this directory for cleanup (except root)
        if rel_path not in [".", ""]:
            dirs_needing_cleanup.add(rel_path)
        
        for filename in filenames:
            # Skip excluded files
            if filename in EXCLUDED_FILES:
                continue
                
            file_path = os.path.join(dirpath, filename)
            rel_file_path = os.path.relpath(file_path, source_dir)
            
            # Create valid WiX IDs
            comp_id = make_id("CMP", rel_file_path)
            file_id = make_id("FILE", rel_file_path)
            
            # Create Component
            comp = ET.SubElement(comp_group, "Component", 
                                 Id=comp_id, 
                                 Guid=str(uuid.uuid4()).upper(), 
                                 Directory=dir_id)
            
            # Registry value for per-user install consistency (required by WiX for per-user)
            ET.SubElement(comp, "RegistryValue", 
                                Root="HKCU", 
                                Key=f"Software\\AirfoilSplines\\Files\\{file_id}",
                                Name="installed", 
                                Type="integer", 
                                Value="1", 
                                Action="write")
            
            # File entry - path relative to setup folder
            file_source_path = f"{source_dir_rel}/{rel_file_path.replace(os.sep, '/')}"
            # Normalize path separators and remove any double slashes
            file_source_path = file_source_path.replace('\\', '/').replace('//', '/')
            ET.SubElement(comp, "File", 
                          Id=file_id, 
                          Source=file_source_path, 
                          KeyPath="yes")
            
            file_count += 1
    
    # 2b. Add RemoveFolder components for each directory to ensure clean uninstall
    if "lib" not in dir_map:
        lib_dir_id = make_id("DIR", "lib")
        dir_map["lib"] = lib_dir_id
    if "lib" not in dirs_needing_cleanup:
        dirs_needing_cleanup.add("lib")
    
    if not exclude_lib:
        for pycache_path in list(pycache_dirs):
            if pycache_path.startswith("lib" + os.sep) or pycache_path.startswith("lib/"):
                parts = pycache_path.split(os.sep) if os.sep in pycache_path else pycache_path.split("/")
                for i in range(1, len(parts)):
                    parent_path = os.sep.join(parts[:i])
                    if parent_path and parent_path not in dir_map:
                        parent_id = make_id("DIR", parent_path)
                        dir_map[parent_path] = parent_id
                    if parent_path and parent_path not in dirs_needing_cleanup:
                        dirs_needing_cleanup.add(parent_path)
    
    # Sort directories by depth (deepest first) to ensure proper removal order
    sorted_dirs = sorted(dirs_needing_cleanup, key=lambda p: p.count(os.sep), reverse=True)
    
    for rel_path in sorted_dirs:
        dir_id = dir_map.get(rel_path, directory_id_root)
        remove_comp_id = make_id("RMDIR", rel_path)
        
        # Create a component specifically for removing this directory
        remove_comp = ET.SubElement(comp_group, "Component",
                                    Id=remove_comp_id,
                                    Guid=str(uuid.uuid4()).upper(),
                                    Directory=dir_id)
        
        # Registry value as KeyPath (required for per-user components)
        ET.SubElement(remove_comp, "RegistryValue",
                      Root="HKCU",
                      Key=f"Software\\AirfoilSplines\\Folders\\{remove_comp_id}",
                      Name="installed",
                      Type="integer",
                      Value="1",
                      Action="write")
        
        # Use RemoveFolderEx for all directory cleanup (works for both empty and non-empty folders)
        util_ns = "http://wixtoolset.org/schemas/v4/wxs/util"
        ET.register_namespace('util', util_ns)
        remove_folder_ex = ET.SubElement(remove_comp, f"{{{util_ns}}}RemoveFolderEx")
        remove_folder_ex.set("Id", f"RF_{make_id('', rel_path)[-60:]}")
        remove_folder_ex.set("On", "uninstall")
        remove_folder_ex.set("Property", dir_id)  # Use directory ID as property
    
    # 2c. Add cleanup components for __pycache__ directories (runtime-generated)
    # These directories contain .pyc files created by Python at runtime
    # First, ensure all parent directories of __pycache__ directories are in dir_map
    for pycache_path in list(pycache_dirs):
        # Ensure parent directories are in dir_map
        parts = pycache_path.split(os.sep) if os.sep in pycache_path else pycache_path.split("/")
        for i in range(1, len(parts)):
            parent_path = os.sep.join(parts[:i])
            if parent_path and parent_path not in dir_map:
                parent_id = make_id("DIR", parent_path)
                dir_map[parent_path] = parent_id
            if parent_path and parent_path not in dirs_needing_cleanup:
                dirs_needing_cleanup.add(parent_path)
    
    for pycache_path in sorted(pycache_dirs):
        pycache_dir_id = dir_map.get(pycache_path)
        if not pycache_dir_id:
            continue
            
        cleanup_comp_id = make_id("PYCACHE", pycache_path)
        
        # Create a component to clean up this __pycache__ directory
        cleanup_comp = ET.SubElement(comp_group, "Component",
                                     Id=cleanup_comp_id,
                                     Guid=str(uuid.uuid4()).upper(),
                                     Directory=pycache_dir_id)
        
        # Registry value as KeyPath (required for per-user components)
        ET.SubElement(cleanup_comp, "RegistryValue",
                      Root="HKCU",
                      Key=f"Software\\AirfoilSplines\\Pycache\\{cleanup_comp_id}",
                      Name="installed",
                      Type="integer",
                      Value="1",
                      Action="write")
        
        # RemoveFile with wildcard to delete all .pyc files
        ET.SubElement(cleanup_comp, "RemoveFile",
                      Id=f"RMF_pyc_{make_id('', pycache_path)[-50:]}",
                      Name="*.pyc",
                      On="uninstall")
        
        # RemoveFile with wildcard to delete all .pyo files (older Python optimization files)
        ET.SubElement(cleanup_comp, "RemoveFile",
                      Id=f"RMF_pyo_{make_id('', pycache_path)[-50:]}",
                      Name="*.pyo",
                      On="uninstall")
        
        # RemoveFolderEx to remove the __pycache__ directory itself (works for non-empty directories)
        util_ns = "http://wixtoolset.org/schemas/v4/wxs/util"
        ET.register_namespace('util', util_ns)
        remove_folder_ex = ET.SubElement(cleanup_comp, f"{{{util_ns}}}RemoveFolderEx")
        remove_folder_ex.set("Id", f"RMD_pyc_{make_id('', pycache_path)[-50:]}")
        remove_folder_ex.set("On", "uninstall")
        remove_folder_ex.set("Property", pycache_dir_id)  # Use directory ID as property

    # 3. Define the directory structure in another fragment
    # First, ensure all parent directories are in dir_map (needed for proper directory structure)
    all_paths = list(dir_map.keys())
    for rel_path in all_paths:
        if rel_path in [".", ""]:
            continue
        parts = rel_path.split(os.sep) if os.sep in rel_path else rel_path.split("/")
        for i in range(1, len(parts)):
            parent_path = os.sep.join(parts[:i])
            if parent_path and parent_path not in dir_map:
                parent_id = make_id("DIR", parent_path)
                dir_map[parent_path] = parent_id
    
    dir_fragment = ET.SubElement(root, "Fragment")
    
    # WiX v4+ uses Directory elements nested inside DirectoryRef
    # Sort by depth to ensure parents are defined before children
    sorted_dir_items = sorted(dir_map.items(), key=lambda x: x[0].count(os.sep) if os.sep in x[0] else x[0].count("/"))
    for rel_path, dir_id in sorted_dir_items:
        if rel_path in [".", ""]:
            continue
        
        parent_rel = os.path.dirname(rel_path)
        parent_id = dir_map.get(parent_rel, directory_id_root)
        
        p_ref = ET.SubElement(dir_fragment, "DirectoryRef", Id=parent_id)
        ET.SubElement(p_ref, "Directory", Id=dir_id, Name=os.path.basename(rel_path))

    # Write XML
    # Always register util namespace since we use RemoveFolderEx for all cleanup
    util_ns_uri = "http://wixtoolset.org/schemas/v4/wxs/util"
    ET.register_namespace('util', util_ns_uri)
    
    xml_str = ET.tostring(root, encoding='unicode')
    
    # Always add util namespace declaration since we use RemoveFolderEx
    if util_ns_uri in xml_str:
        # Replace the Wix opening tag to include util namespace
        xml_str = xml_str.replace('<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">',
                                  '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs" xmlns:util="http://wixtoolset.org/schemas/v4/wxs/util">')
        # Replace fully qualified namespace URI with prefix
        xml_str = xml_str.replace(f'{{{util_ns_uri}}}', 'util:')
    
    # Parse and pretty-print
    xml_dom = minidom.parseString(xml_str)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(xml_dom.toprettyxml(indent="    "))
    
    variant = "without lib" if exclude_lib else "with lib"
    print(f"Generated {output_file} (WiX v4+) with {file_count} files ({variant}).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate WiX fragment file for installer')
    parser.add_argument('--exclude-lib', action='store_true',
                        help='Exclude the lib directory from the installer (for standalone version)')
    parser.add_argument('--output', default='Files.wxs',
                        help='Output file name (default: Files.wxs)')
    parser.add_argument('--source-dir', default='..',
                        help='Source directory to scan for files (default: ..)')
    args = parser.parse_args()
    
    generate_wxs_fragment(
        source_dir=args.source_dir,
        output_file=args.output,
        component_group_id="HarvestedAddInFiles",
        directory_id_root="ContentsFolder",
        exclude_lib=args.exclude_lib
    )
