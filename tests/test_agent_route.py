import json
import os
import requests


def main() -> None:
    url = "http://localhost:8000/v1/run-agent"
    session_id = None
    token = os.getenv("SUPABASE_USER_JWT")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    while True: 
        query = input("Query: ")
        payload = {"query": query, "app": "gmail", "session_id": session_id}
        resp = requests.post(url, json=payload, stream=True, headers=headers)
        print("status:", resp.status_code)
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                print(line)
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                resp_json = json.loads(data)
            except Exception:
                continue
            if resp_json.get("type") == "session_id":
                session_id = resp_json.get("session_id")
                print("Session ID:", session_id)
        if query == "quit":
            break

if __name__ == "__main__":
    main()
