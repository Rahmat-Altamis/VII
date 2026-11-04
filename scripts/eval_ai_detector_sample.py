"""Evaluate hosted VLM-as-detector on a stratified sample (40 images).

Sends each image to the configured Meta model with a JSON verdict
prompt, records verdict/confidence/reasons, and reports accuracy. Live
provider calls (40); run only when explicitly authorized.
"""
from __future__ import annotations

import base64
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vii.config import get_settings  # noqa: E402
from vii.meta.client import MetaClient  # noqa: E402
from vii.meta.response_parser import output_text  # noqa: E402

PROMPT = """You are a synthetic-media analyst. Decide whether this image is
AI-generated or a real photo/painting. Look for generation tells
(anatomy errors, garbled text, inconsistent lighting, plastic skin,
impossible geometry) versus camera/paint evidence (sensor noise,
natural imperfections, artist brushwork). Return ONLY a JSON object:
{"verdict": "ai_generated"|"real", "confidence": 0.0-1.0,
"reasons": ["short reason", ...]}"""


def main() -> int:
    s = get_settings()
    client = MetaClient(s.effective_api_key, s.meta_base_url, s.meta_model,
                        s.request_timeout_s, 0, s.meta_transcription_model)
    rows = [json.loads(ln) for ln in
            open("data/evaluation/ai_detection/manifest.jsonl")]
    random.seed(7)
    ai = random.sample([r for r in rows if r["label"] == "ai_generated"], 20)
    real = random.sample([r for r in rows if r["label"] == "real"], 20)
    sample = ai + real
    random.shuffle(sample)
    results = []
    for i, r in enumerate(sample):
        img = Path("data/evaluation/ai_detection/raw") / r["path"]
        data = base64.b64encode(img.read_bytes()).decode()
        payload = {"model": s.meta_model,
                   "input": [{"role": "user", "content": [
                       {"type": "input_text", "text": PROMPT},
                       {"type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{data}"}]}]}
        t0 = time.time()
        try:
            resp = client.responses_create(payload)
            text = output_text(resp if isinstance(resp, dict) else {})
            start, end = text.find("{"), text.rfind("}")
            parsed = json.loads(text[start:end + 1])
            verdict = parsed.get("verdict", "")
            conf = float(parsed.get("confidence", 0) or 0)
            reasons = parsed.get("reasons", [])
            error = ""
        except Exception as e:
            verdict, conf, reasons = "", 0.0, []
            error = f"{type(e).__name__}: {str(e)[:200]}"
        ok = verdict == r["label"]
        results.append({"image_id": r["image_id"], "label": r["label"],
                        "verdict": verdict, "confidence": round(conf, 3),
                        "correct": ok, "error": error, "reasons": reasons,
                        "latency_s": round(time.time() - t0, 1)})
        print(f"{i+1}/40 {r['image_id']} label={r['label']} "
              f"verdict={verdict} ok={ok} {error}", flush=True)
    correct = sum(1 for x in results if x["correct"])
    by_label = {}
    for label in ("ai_generated", "real"):
        sub = [x for x in results if x["label"] == label]
        by_label[label] = sum(1 for x in sub if x["correct"]) / len(sub)
    report = {"n": len(results), "accuracy": round(correct / len(results), 3),
              "by_label": {k: round(v, 3) for k, v in by_label.items()},
              "results": results}
    Path("data/evaluation/ai_detection/eval_sample.json").write_text(
        json.dumps(report, indent=2))
    print(f"ACCURACY: {report['accuracy']} by_label={report['by_label']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
