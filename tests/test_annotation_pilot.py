"""Pilot sampling and usage accounting, without invoking any model."""
import unittest

from tools.run_annotation_pilot import (
    CELLS,
    choose_sample,
    parse_response,
    prompt_parts,
    read_jsonl,
)


class PilotTests(unittest.TestCase):
    def corpus(self):
        docs = []
        sources = ["gsearch_us_2022", "us_open_2026", "wayback_vn_2022", "tinix_vn"]
        for cell, source in zip(CELLS, sources):
            for i in range(20):
                docs.append({"doc_id": f"{len(docs):016x}", "source": source,
                             "era": cell[-4:], "da_family": True, "region": "VN",
                             "title": "Data Analyst", "text": "Build SQL reports."})
        return docs

    def test_sample_is_order_independent_seeded_balanced_and_public(self):
        docs = self.corpus()
        docs.append(dict(docs[0], source="pasted_2026", doc_id="f" * 16))
        a = choose_sample(docs, 20261017)
        b = choose_sample(list(reversed(docs)), 20261017)
        self.assertEqual(a, b)
        self.assertEqual(len(a), 50)
        self.assertEqual([sum(d['cell'] == c for d in a) for c in CELLS], [13, 13, 12, 12])
        self.assertEqual(len({d['doc_id'] for d in a}), 50)
        self.assertNotIn("pasted_2026", {d['source'] for d in a})
        self.assertNotEqual(a, choose_sample(docs, 2))

    def test_sample_rejects_short_cells_and_duplicate_identity(self):
        with self.assertRaises(ValueError):
            choose_sample([], 1)
        docs = self.corpus()
        docs.append(docs[0].copy())
        with self.assertRaises(ValueError):
            choose_sample(docs, 1)

    def test_prompt_separates_fixed_and_posting(self):
        fixed, posting = prompt_parts(self.corpus()[0], "schema", "guide", "taxonomy", "version")
        self.assertNotIn("Build SQL reports.", fixed)
        self.assertEqual(__import__('json').loads(posting)['text'], 'Build SQL reports.')
        self.assertIn("version", fixed)

    def test_usage_is_counted_once_not_once_per_event(self):
        message = {"role": "assistant", "model": "gpt-6.1-sol", "stopReason": "stop",
                   "content": [{"type": "text", "text": '{"ok":true}'}],
                   "usage": {"input": 50, "cacheRead": 100, "output": 20,
                             "totalTokens": 170, "reasoning": 2}}
        events = [{"type": "message_end", "message": message},
                  {"type": "turn_end", "message": message},
                  {"type": "agent_end", "messages": [message]}]
        result = parse_response(events)
        self.assertEqual(result['input_tokens'], 150)
        self.assertEqual(result['uncached_input_tokens'], 50)
        self.assertEqual(result['output_tokens'], 20)
        self.assertEqual(result['record'], {'ok': True})

    def test_cli_recovered_transport_failure_keeps_success_and_counts_usage(self):
        failed = {"role": "assistant", "stopReason": "error", "content": [],
                  "usage": {"input": 10, "output": 0, "totalTokens": 10}}
        good = {"role": "assistant", "model": "gpt-6.1-sol", "stopReason": "stop",
                "content": [{"type": "text", "text": '{}'}],
                "usage": {"input": 50, "output": 20, "totalTokens": 70}}
        events = [{"type": "message_end", "message": m} for m in [failed, good]]
        result = parse_response(events)
        self.assertEqual(result['input_tokens'], 60)
        self.assertEqual(result['cli_error_events'], 1)
        self.assertEqual(result['record'], {})

    def test_jsonl_preserves_unicode_line_separators_in_text(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.jsonl'
            value = {'text': 'fictional\u2028posting\u0085text'}
            path.write_text(json.dumps(value, ensure_ascii=False) + '\n')
            self.assertEqual(read_jsonl(path), [value])

    def test_bad_model_response_is_not_silently_repaired(self):
        with self.assertRaises(ValueError):
            parse_response([])
        message = {"role": "assistant", "stopReason": "error", "content": []}
        with self.assertRaises(ValueError):
            parse_response([{"type": "message_end", "message": message}])


if __name__ == '__main__':
    unittest.main()
