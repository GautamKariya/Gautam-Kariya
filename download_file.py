import requests
import os
from tqdm import tqdm
from urllib.parse import urlparse, unquote
from email.message import EmailMessage

def get_filename_from_cd(cd):
    """
    Get filename from content-disposition
    """
    if not cd:
        return None
    msg = EmailMessage()
    msg['content-disposition'] = cd
    return msg.get_filename()

def download_file(url):
    try:
        # Send a GET request with stream=True to get headers first
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, stream=True, headers=headers)
        response.raise_for_status()  # Check for HTTP errors

        # get filename
        filename = get_filename_from_cd(response.headers.get("content-disposition"))

        if not filename:
             # if no content-disposition, parse url
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)

        # Decode filename just in case it's URL encoded
        if filename:
            filename = unquote(filename)

        # Sanitize filename to prevent path traversal
        if filename:
            filename = os.path.basename(filename)

        # Fallback if filename is still empty (e.g. url ends with /)
        if not filename:
            filename = "downloaded_file"

        # Total size in bytes.
        total_size = int(response.headers.get('content-length', 0))

        block_size = 1024 # 1 Kibibyte

        # Setup progress bar
        tqdm_bar = tqdm(total=total_size, unit='iB', unit_scale=True)

        with open(filename, 'wb') as file:
            for data in response.iter_content(block_size):
                tqdm_bar.update(len(data))
                file.write(data)
        tqdm_bar.close()

        if total_size != 0 and tqdm_bar.n != total_size:
            print("ERROR, something went wrong")
        else:
            print(f"File downloaded successfully as: {filename}")

    except requests.exceptions.RequestException as e:
        print(f"Error downloading file: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    try:
        url = input("Please enter the URL: ")
        if url.strip():
            download_file(url.strip())
        else:
            print("No URL provided.")
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
