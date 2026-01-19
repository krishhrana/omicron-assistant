import json
import requests


def main() -> None:
    url = "http://localhost:8000/v1/run-agent/"
    session_id = None
    while True: 
        query = input("Query: ")
        payload = {"query": query, "app": "gmail", "session_id": session_id}
        resp = requests.post(url, json=payload, stream=True)
        print("status:", resp.status_code)
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                print(line)
            try: 
                resp_json = json.loads(line)
                if resp_json['type'] == 'session_id':
                    session_id = resp_json['session_id']
                    print("Session ID:", session_id)
            except: 
                pass
        if query == "quit":
            break

if __name__ == "__main__":
    main()
