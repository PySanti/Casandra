import json

def read_api_keys(path : str):
    with open(path, 'r') as f:
        data = json.load(f)
    return data

