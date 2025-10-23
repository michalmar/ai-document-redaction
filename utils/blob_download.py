"""
Simple utility to download Azure Blob Storage files using Entra ID authentication.

Usage:
    python blob_download.py <blob_url>

Example:
    python blob_download.py https://account.blob.core.windows.net/container/path/file.doc
"""

import sys
import os
from urllib.parse import urlparse, unquote
from azure.storage.blob import BlobClient
from azure.identity import DefaultAzureCredential


def download_blob(blob_url: str, output_dir: str = ".") -> str:
    """
    Download a blob from Azure Storage using Entra ID authentication.
    
    Args:
        blob_url: Full URL to the blob
        output_dir: Directory where the file will be saved (default: current directory)
    
    Returns:
        Path to the downloaded file
    
    Raises:
        ValueError: If the URL is invalid
        Exception: If download fails
    """
    # Parse the blob URL
    parsed_url = urlparse(blob_url)
    if not parsed_url.scheme or not parsed_url.netloc:
        raise ValueError(f"Invalid blob URL: {blob_url}")
    
    # Extract filename from path
    path_parts = parsed_url.path.strip('/').split('/')
    if len(path_parts) < 2:
        raise ValueError(f"Invalid blob path in URL: {blob_url}")
    
    filename = unquote(path_parts[-1])
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, filename)
    
    # Create blob client with Entra ID authentication
    credential = DefaultAzureCredential()
    blob_client = BlobClient.from_blob_url(blob_url, credential=credential)
    
    print(f"Downloading: {filename}")
    print(f"From: {blob_url}")
    print(f"To: {output_path}")
    
    # Download the blob
    with open(output_path, "wb") as file:
        download_stream = blob_client.download_blob()
        file.write(download_stream.readall())
    
    print(f"✓ Download complete: {output_path}")
    return output_path


def main():
    """Main entry point for the script."""
    if len(sys.argv) != 2:
        print("Usage: python blob_download.py <blob_url>")
        print("\nExample:")
        print("  python blob_download.py https://account.blob.core.windows.net/container/file.doc")
        sys.exit(1)
    
    blob_url = sys.argv[1]
    
    try:
        output_path = download_blob(blob_url)
        sys.exit(0)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
