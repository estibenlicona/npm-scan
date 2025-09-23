import requests

# Send a GET request to a URL
response = requests.get('https://pypi.org/pypi/requests/json')  # type: ignore

# Access the response content (e.g., as JSON)
data = response.json()

urls = data.get("urls", [])

print(urls[0].get("packagetype", ""))
