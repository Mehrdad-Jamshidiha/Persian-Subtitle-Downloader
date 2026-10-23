#!/usr/bin/env python3
"""
Scrape subkade.ir for movie subtitles by IMDb ID
Usage: python scrape_subkade.py <tt1225831,tt0137523,tt0068646>
"""

import requests
import re
import sys
import os
import time

BASE_URL = "https://subkade.ir"
DOWNLOAD_BASE = "https://dl1.subkade.ir"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def search_movie(imdb_id):
    """Search subkade.ir for movie by IMDb ID"""
    # Remove leading tt if already present
    if imdb_id.startswith('tt'):
        imdb_id = imdb_id[2:]
    search_url = f"{BASE_URL}/?s=tt{imdb_id}"
    print(f"Searching: {search_url}")
    
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error searching {imdb_id}: {e}")
        return None

def find_download_page(html, imdb_id):
    """Find the download page link for the movie"""
    download_pattern = r'href=["\']([^"\s]+)["\']'
    
    links = re.findall(download_pattern, html)
    
    # Look for download page with URL-encoded Persian characters and movie name
    for link in links:
        if '%d8%af%d8%a7%d9%86%d9%84%d9%88%d8%af' in link and imdb_id.lower() in link.lower():
            return link
    
    # Fallback: look for any link with URL-encoded Persian chars
    for link in links:
        if '%d8%af%d8%a7%d9%86%d9%84%d9%88%d8%af' in link:
            return link
    
    return None

def navigate_to_download_page(download_url):
    """Navigate to download page and get the zip file URL"""
    print(f"Navigating to: {download_url}")
    
    try:
        response = requests.get(download_url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error navigating to {download_url}: {e}")
        return None

def find_zip_download(html):
    """Find the zip download link"""
    # Pattern: wp-content/uploads/{year}/{month}/{movie}.zip
    zip_pattern = r'wp-content/uploads/[^"\s]+\.zip'
    
    zip_links = re.findall(zip_pattern, html)
    
    if zip_links:
        # Return the dl1.subkade.ir version (add leading slash)
        return f"{DOWNLOAD_BASE}/{zip_links[0]}"
    
    return None

def download_file(url, output_path=None):
    """Download the zip file"""
    if output_path is None:
        filename = url.split('/')[-1]
        output_path = filename
    
    print(f"Downloading: {url}")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=60, stream=True)
        response.raise_for_status()
        
        # Save the file
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"Saved: {output_path}")
        return True
    except Exception as e:
        print(f"Download failed: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python scrape_subkade.py <tt1225831,tt0137523,...>")
        print("Example: python scrape_subkade.py tt1225831,tt0137523")
        sys.exit(1)
    
    imdb_ids = [x.strip() for x in sys.argv[1].split(',')]
    
    for imdb_id in imdb_ids:
        if not imdb_id.startswith('tt'):
            imdb_id = 'tt' + imdb_id
        
        # Step 1: Search
        html = search_movie(imdb_id)
        if not html:
            print(f"Skipping {imdb_id}: search failed")
            continue
        
        # Step 2: Find download page
        download_page = find_download_page(html, imdb_id)
        if not download_page:
            print(f"Skipping {imdb_id}: no download page found")
            continue
        
        # Step 3: Navigate to download page
        download_html = navigate_to_download_page(download_page)
        if not download_html:
            print(f"Skipping {imdb_id}: failed to navigate")
            continue
        
        # Step 4: Find zip download
        zip_url = find_zip_download(download_html)
        if not zip_url:
            print(f"Skipping {imdb_id}: no zip download found")
            continue
        
        # Step 5: Download
        output_file = f"{imdb_id}.zip"
        download_file(zip_url, output_file)
        
        print()
        time.sleep(1)  # Be polite to the server
    
    print("Done!")

if __name__ == "__main__":
    main()
