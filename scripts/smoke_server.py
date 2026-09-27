import urllib.request
import time
import sys

# Wait for Streamlit to start up
time.sleep(5)

url = "http://localhost:8501"
print(f"Testing {url}...")
try:
    response = urllib.request.urlopen(url)
    if response.getcode() == 200:
        print("SUCCESS! Streamlit is running and responding to requests.")
        sys.exit(0)
    else:
        print(f"FAILED. Received status code: {response.getcode()}")
        sys.exit(1)
except Exception as e:
    print(f"FAILED to connect: {e}")
    sys.exit(1)
