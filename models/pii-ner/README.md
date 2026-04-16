# PII NER ONNX (optional)

Place a token-classification NER model and HuggingFace `tokenizer.json` here, then set:

- `AG_PII_NER_ONNX` — path to `.onnx`
- `AG_PII_NER_TOKENIZER` — path to `tokenizer.json`

Inputs must include `input_ids`, `attention_mask`, and `token_type_ids` (BERT-style). Without these paths, `ag-pii-onnx` and `antigravity_core` fall back to regex-only detection.
