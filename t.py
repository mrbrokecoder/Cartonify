import requests

url = "https://4000-mrbrokecoder-cartonify-e8aktd6fbpq.ws-us115.gitpod.io/api/transform"
headers = {
    "X-API-Key": "J3WzhAG2Ytyub7RBFfcKTZgcMvIFCNbGeQn1ep6SpKZ1Z6fYD-V2TmAT-8na6Ij0"
}
data = {
    "image_size": "512x512",
    "style": "anime",
    "color": "vibrant",
    "prompt": "A beautiful landscape"
}

response = requests.post(url, headers=headers, json=data)

# Add these lines to print response information
print(f"Status Code: {response.status_code}")
print(f"Response Content: {response.text}")

# Then try to parse the JSON
try:
    result = response.json()
    print(f"Parsed JSON: {result}")
except requests.exceptions.JSONDecodeError as e:
    print(f"JSON Decode Error: {e}")
    print(f"Raw response content: {response.content}")