import json

from middle import main


def mocked_gemini_response(prompt_payload):
    # Return a fake Gemini JSON matching the responseSchema used in structure_response
    gemini_out = {
        "summary": "- Food establishment: means any place where food is prepared or served. (§81.07)\\n- Cutting boards must be cleaned and sanitized after use. (§81.08)",
        "citations": [
            {"index": 0, "relevant_passages": ["Food establishment: means any place where food is prepared or served."]},
            {"index": 1, "relevant_passages": ["Cutting boards must be cleaned and sanitized after use."]}
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
    # Monkeypatch _gemini_post in middle.main
    original = main._gemini_post
    try:
        main._gemini_post = lambda url, payload: mocked_gemini_response(payload)

        # Create fake pinecone_matches with two sources
        matches = [
            {"metadata": {"code": "NYC Health Code", "section": "81.07", "section_title": "Food protection", "source_url": "https://example.com/nyc-health-code#81.07", "text": "Food establishment: means any place where food is prepared or served."}},
            {"metadata": {"code": "NYC Health Code", "section": "81.08", "section_title": "Equipment", "source_url": "https://example.com/nyc-health-code#81.08", "text": "Cutting boards must be cleaned and sanitized after use."}},
        ]

        out = main.structure_response("Can I use plastic cutting boards?", matches)
        print(json.dumps(out, indent=2))
    finally:
        main._gemini_post = original


if __name__ == "__main__":
    run_test()
