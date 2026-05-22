import json

from middle import main


def mocked_gemini_response(prompt_payload):
    # Simulate Gemini returning a short, verbatim definition bullet plus a rule
    gemini_out = {
        "summary": "- "
                   "Operator: means the person responsible for the establishment's operations. (§14-1.21)\\n- Operators must ensure contaminated water is not used for food preparation. (§14-1.21)",
        "citations": [
            {"index": 0, "relevant_passages": [
                "Operator: means the person responsible for the establishment's operations."
            ]},
            {"index": 1, "relevant_passages": [
                "Operators must ensure contaminated water is not used for food preparation."
            ]}
        ]
    }
    wrapped = {"candidates": [{"content": {"parts": [{"text": json.dumps(gemini_out)}]}}]}

    class Resp:
        def __init__(self, data):
            self._data = data
            self.status_code = 200

        def json(self):
            return self._data

    return Resp(wrapped)


def run_test():
    original = main._gemini_post
    try:
        main._gemini_post = lambda url, payload: mocked_gemini_response(payload)

        matches = [
            {"metadata": {"code": "NYS Sanitary Code", "section": "14-1.21", "section_title": "Definitions/Operators", "source_url": "https://example.com/nys-sanitary#14-1.21", "text": "Operator: means the person responsible for the establishment's operations."}},
            {"metadata": {"code": "NYS Sanitary Code", "section": "14-1.21", "section_title": "Definitions/Operators", "source_url": "https://example.com/nys-sanitary#14-1.21", "text": "Operators must ensure contaminated water is not used for food preparation."}},
        ]

        out = main.structure_response("What is an operator and responsibilities?", matches)
        print(json.dumps(out, indent=2))
    finally:
        main._gemini_post = original


if __name__ == "__main__":
    run_test()
