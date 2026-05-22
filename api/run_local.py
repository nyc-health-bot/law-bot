import os
from flask import Flask, request, make_response

# Run the cloud-function-style handler locally for debugging/startup reproduction.
app = Flask(__name__)

# Import the function module and monkeypatch prompt loader to use local files
import middle.google_function as gf

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

def _local_get_prompt(name: str) -> str:
    path = os.path.join(PROMPTS_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()

gf._get_prompt = _local_get_prompt


@app.route("/", methods=["POST", "OPTIONS"])
def handle():
    try:
        result = gf.handle_request(request)
        # handle_request may return (body, status, headers) or JSON body
        if isinstance(result, tuple):
            body, status, headers = result
            resp = make_response(body, status)
            for k, v in headers.items():
                resp.headers[k] = v
            return resp
        else:
            return result
    except Exception as e:
        return ({"error": str(e)}, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting local server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
