#!/usr/bin/env python3
"""
Standalone script to display folder structure in a tree-like format.

Supports both local filesystem and Azure Blob Storage containers.

Usage:
    # Local filesystem
    python folder_structure.py [path]
    
    # Azure Blob Storage
    python folder_structure.py --azure --storage-account <name> --container <name> [--prefix <prefix>]
    
If no path is provided, uses current directory.
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import List, Dict, Set, Optional
from collections import defaultdict


class TreeNode:
    """Represents a node in the file tree."""
    
    def __init__(self, name: str, is_dir: bool = False):
        self.name = name
        self.is_dir = is_dir
        self.children: Dict[str, 'TreeNode'] = {}
    
    def add_path(self, parts: List[str], is_file: bool = False):
        """Add a path to the tree structure."""
        if not parts:
            return
        
        current = parts[0]
        remaining = parts[1:]
        
        # Check if this is the last part (the actual file/folder)
        is_last = len(remaining) == 0
        
        if current not in self.children:
            # If it's the last part and it's a file, mark as file
            # Otherwise, it's a directory
            self.children[current] = TreeNode(current, is_dir=not (is_last and is_file))
        
        if remaining:
            self.children[current].add_path(remaining, is_file)


def build_tree_from_blob_list(blob_names: List[str], prefix: str = "") -> TreeNode:
    """
    Build a tree structure from a flat list of blob names.
    
    Args:
        blob_names: List of blob paths (e.g., ['log/test.txt', 'log/sub/file.txt'])
        prefix: Optional prefix to filter blobs
        
    Returns:
        Root TreeNode
    """
    root = TreeNode("root", is_dir=True)
    
    for blob_name in blob_names:
        # Skip if doesn't match prefix
        if prefix and not blob_name.startswith(prefix):
            continue
        
        # Remove prefix if specified
        relative_path = blob_name[len(prefix):].lstrip('/') if prefix else blob_name
        
        if not relative_path:
            continue
        
        # Split path into parts
        parts = relative_path.split('/')
        
        # Add to tree (last part is the file)
        root.add_path(parts, is_file=True)
    
    return root


def get_file_icon(filename: str) -> str:
    """
    Get an icon for a file based on its extension.
    
    Args:
        filename: Name of the file
        
    Returns:
        Icon emoji
    """
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    
    icon_map = {
        # Documents
        'pdf': '📄',
        'doc': '📝',
        'docx': '📝',
        'txt': '📃',
        'md': '📋',
        'rtf': '📝',
        
        # Spreadsheets
        'xls': '📊',
        'xlsx': '📊',
        'xlsm': '📊',
        'csv': '📊',
        
        # Images
        'jpg': '🖼️',
        'jpeg': '🖼️',
        'png': '🖼️',
        'gif': '🖼️',
        'bmp': '🖼️',
        'svg': '🖼️',
        
        # Archives
        'zip': '📦',
        'rar': '📦',
        'tar': '📦',
        'gz': '📦',
        '7z': '📦',
        
        # Code
        'py': '🐍',
        'js': '📜',
        'ts': '📜',
        'java': '☕',
        'cpp': '⚙️',
        'c': '⚙️',
        'go': '🔷',
        'rs': '🦀',
        
        # Web
        'html': '🌐',
        'css': '🎨',
        'json': '📋',
        'xml': '📋',
        'yaml': '📋',
        'yml': '📋',
        
        # Logs
        'log': '📋',
        
        # Others
        'ppt': '📊',
        'pptx': '📊',
    }
    
    return icon_map.get(ext, '📄')


def format_tree_node(
    node: TreeNode,
    prefix: str = "",
    is_last: bool = True,
    show_root: bool = False
) -> List[str]:
    """
    Format a TreeNode into tree-style lines.
    
    Args:
        node: TreeNode to format
        prefix: Current line prefix
        is_last: Whether this is the last item in parent
        show_root: Whether to show the root node
        
    Returns:
        List of formatted lines
    """
    lines = []
    
    # Add current node if not root or if showing root
    if show_root or node.name != "root":
        connector = "└── " if is_last else "├── "
        
        # Add icon based on type
        if node.is_dir:
            icon = "📁 "
            item_name = node.name
        else:
            icon = get_file_icon(node.name) + " "
            item_name = node.name
        
        if prefix:
            lines.append(f"{prefix}{connector}{icon}{item_name}")
        else:
            lines.append(f"{icon}{item_name}")
    
    # Sort children: directories first, then alphabetically
    sorted_children = sorted(
        node.children.items(),
        key=lambda x: (not x[1].is_dir, x[0].lower())
    )
    
    # Process children
    for index, (child_name, child_node) in enumerate(sorted_children):
        is_last_child = (index == len(sorted_children) - 1)
        
        # Determine extension for children
        if show_root or node.name != "root":
            if is_last:
                extension = "    "
            else:
                extension = "│   "
            child_prefix = prefix + extension
        else:
            child_prefix = prefix
        
        child_lines = format_tree_node(
            child_node,
            prefix=child_prefix,
            is_last=is_last_child,
            show_root=True
        )
        lines.extend(child_lines)
    
    return lines


async def get_azure_blob_tree(
    storage_account: str,
    container: str,
    prefix: str = "",
    max_depth: int = -1
) -> List[str]:
    """
    Get tree structure from Azure Blob Storage container.
    
    Args:
        storage_account: Storage account name
        container: Container name
        prefix: Optional blob prefix to filter
        max_depth: Maximum depth (not fully implemented for Azure yet)
        
    Returns:
        List of formatted tree lines
    """
    try:
        from azure.identity.aio import DefaultAzureCredential
        from azure.storage.blob.aio import BlobServiceClient
    except ImportError:
        return ["Error: azure-identity and azure-storage-blob packages required for Azure support"]
    
    account_url = f"https://{storage_account}.blob.core.windows.net"
    credential = DefaultAzureCredential()
    
    try:
        async with BlobServiceClient(account_url=account_url, credential=credential) as client:
            container_client = client.get_container_client(container)
            
            # List all blobs
            blob_names = []
            async for blob in container_client.list_blobs(name_starts_with=prefix):
                blob_names.append(blob.name)
            
            if not blob_names:
                return [f"{container}/ (empty)"]
            
            # Build tree structure
            tree = build_tree_from_blob_list(blob_names, prefix)
            
            # Format output
            lines = [f"📦 {container}/"]
            lines.extend(format_tree_node(tree, show_root=False)[1:])  # Skip root
            
            return lines
            
    except Exception as e:
        return [f"Error accessing Azure Storage: {str(e)}"]
    finally:
        await credential.close()


def get_tree_structure(
    root_path: Path,
    prefix: str = "",
    is_last: bool = True,
    max_depth: int = -1,
    current_depth: int = 0,
    show_hidden: bool = False
) -> List[str]:
    """
    Generate tree structure for a directory.
    
    Args:
        root_path: Root directory path
        prefix: Current line prefix for tree formatting
        is_last: Whether this is the last item in parent directory
        max_depth: Maximum depth to traverse (-1 for unlimited)
        current_depth: Current depth level
        show_hidden: Whether to show hidden files/folders
        
    Returns:
        List of formatted tree lines
    """
    lines = []
    
    if not root_path.exists():
        return [f"Error: Path '{root_path}' does not exist"]
    
    if not root_path.is_dir():
        return [f"Error: Path '{root_path}' is not a directory"]
    
    # Add root directory name
    if current_depth == 0:
        lines.append(f"📁 {root_path.name}")
    
    # Check depth limit
    if max_depth >= 0 and current_depth >= max_depth:
        return lines
    
    try:
        # Get all items in directory
        items = sorted(root_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        
        # Filter hidden files if needed
        if not show_hidden:
            items = [item for item in items if not item.name.startswith('.')]
        
        # Process each item
        for index, item in enumerate(items):
            is_last_item = (index == len(items) - 1)
            
            # Determine tree characters
            if is_last_item:
                connector = "└── "
                extension = "    "
            else:
                connector = "├── "
                extension = "│   "
            
            # Add item name with icon
            if item.is_dir():
                icon = "📁 "
                item_name = item.name
            else:
                icon = get_file_icon(item.name) + " "
                item_name = item.name
            
            lines.append(f"{prefix}{connector}{icon}{item_name}")
            
            # Recursively process subdirectories
            if item.is_dir():
                sub_lines = get_tree_structure(
                    item,
                    prefix=prefix + extension,
                    is_last=is_last_item,
                    max_depth=max_depth,
                    current_depth=current_depth + 1,
                    show_hidden=show_hidden
                )
                lines.extend(sub_lines[1:])  # Skip root name from subdirectory
                
    except PermissionError:
        lines.append(f"{prefix}[Permission Denied]")
    
    return lines


def print_tree(
    path: str = ".",
    max_depth: int = -1,
    show_hidden: bool = False
) -> None:
    """
    Print directory tree structure.
    
    Args:
        path: Directory path to display
        max_depth: Maximum depth to traverse (-1 for unlimited)
        show_hidden: Whether to show hidden files/folders
    """
    root = Path(path).resolve()
    tree_lines = get_tree_structure(
        root,
        max_depth=max_depth,
        show_hidden=show_hidden
    )
    
    for line in tree_lines:
        print(line)


def main():
    """Main entry point for standalone script."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Display folder structure in a tree-like format (local or Azure Blob Storage)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local filesystem
  python folder_structure.py
  python folder_structure.py ./output
  python folder_structure.py ./output --max-depth 3
  
  # Azure Blob Storage
  python folder_structure.py --azure --storage-account mystorageaccount --container mycontainer
  python folder_structure.py --azure --storage-account mystorageaccount --container mycontainer --prefix log/
  python folder_structure.py --azure -s mystorageaccount -c mycontainer
        """
    )
    
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Directory path to display (default: current directory, ignored if --azure is used)"
    )
    
    parser.add_argument(
        "--azure",
        action="store_true",
        help="Use Azure Blob Storage instead of local filesystem"
    )
    
    parser.add_argument(
        "-s", "--storage-account",
        type=str,
        help="Azure Storage account name (required if --azure is used)"
    )
    
    parser.add_argument(
        "-c", "--container",
        type=str,
        help="Azure Blob Storage container name (required if --azure is used)"
    )
    
    parser.add_argument(
        "--prefix",
        type=str,
        default="",
        help="Blob prefix to filter (Azure only, e.g., 'log/' to show only log folder)"
    )
    
    parser.add_argument(
        "-d", "--max-depth",
        type=int,
        default=-1,
        help="Maximum depth to traverse (-1 for unlimited, default: -1)"
    )
    
    parser.add_argument(
        "-a", "--show-hidden",
        action="store_true",
        help="Show hidden files and folders (local filesystem only)"
    )
    
    args = parser.parse_args()
    
    if args.azure:
        # Azure Blob Storage mode
        if not args.storage_account or not args.container:
            parser.error("--storage-account and --container are required when using --azure")
        
        # Run async function
        tree_lines = asyncio.run(get_azure_blob_tree(
            storage_account=args.storage_account,
            container=args.container,
            prefix=args.prefix,
            max_depth=args.max_depth
        ))
        
        for line in tree_lines:
            print(line)
    else:
        # Local filesystem mode
        print_tree(
            path=args.path,
            max_depth=args.max_depth,
            show_hidden=args.show_hidden
        )


if __name__ == "__main__":
    main()
