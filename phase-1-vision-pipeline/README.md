# TopoForge-AI - phase 1: topology perception pipeline

Network diagram image -> **YOLO** (devices) + **PaddleOCR** (text) + **OpenCV** (cables) ->
**Spatial-Semantic Fusion** -> **Address Resolver** -> **graph** -> `outputs/topology.json`.

No RAG, LangGraph, LLM, Terraform or Ansible in this phase. The guiding rule:

> A partially empty but correct `topology.json` is better than a complete one containing guessed data.

**Two outputs:** `topology.json` is the rich canonical file (confidence, provenance, all addresses, `unresolved`) and is stored.
`topology.simple.json` is the minimal `{devices, links}` form and is **the only file handed to the RAG**; it is a pure projection of `topology.json`.

Anything not detected, ambiguous, or below a confidence threshold is `null` (scalars) or `[]`
(collections) and the evidence is preserved under `unresolved`.

IPv4 and IPv6 are both read (`192.168.1.10/24`, `2001:db8:1::10/64`, suffixes `.2` and `::2`).
IPv6 goes in separate `network6` blocks, so IPv4-only output is unchanged.

**Before the RAG:** `topology.simple.json` is checked and the result is written to `validation.json`
(duplicate IPs, masks read as IPs, bad or mismatched masks, network or broadcast addresses, overlapping networks,
VLSM capacity, plus the RAG's own readiness rules). If something is wrong, the user either fixes it (`correct`,
every input strictly checked) or picks `autoaddress` (a fresh VLSM plan). This repeats until it is valid.

## Setup

```bash
python3.13 -m venv .venv && source .venv/bin/activate     # 3.10-3.13 verified with ultralytics 8.4 / paddleocr 3.7
pip install -r requirements.txt
cp /path/to/your/weights.pt models/yolo/best.pt            # <- YOUR YOLO WEIGHTS GO HERE
```

## Run

```bash
# whole pipeline on one image -> outputs/{raw_yolo,raw_ocr,raw_opencv,fusion,topology,topology.simple,validation}.json
python -m vision_pipeline run --image path/to/diagram.png
python -m vision_pipeline run --image d.png --weights /other/best.pt --output-dir out/ --config my.yaml

# stages on their own (each writes its raw JSON)
python -m vision_pipeline yolo   --image d.png
python -m vision_pipeline ocr    --image d.png
python -m vision_pipeline opencv --image d.png --raw-yolo outputs/raw_yolo.json --raw-ocr outputs/raw_ocr.json
python -m vision_pipeline fuse                      # raw_*.json -> fusion.json + topology.json + topology.simple.json

# check / fix the RAG input (exit code 0 = valid)
python -m vision_pipeline validate                  # topology.simple.json -> validation.json
python -m vision_pipeline correct --corrections '[{"device": "PC2", "ip": "192.168.1.11/24"}]'
python -m vision_pipeline autoaddress --ipv4-base 192.168.0.0/16 [--ipv6-base 2001:db8::/48] [--ipv6-vlsm]

python -m vision_pipeline print-config              # every setting and threshold, as JSON
python -m examples.synthetic_demo                   # no weights needed: real OpenCV+fusion on a drawn diagram
python -m pytest                                    # tests (YOLO/OCR adapters are tested with fakes)
```

`fuse` is the swap point: any detector that writes the standard raw JSON (`vision_pipeline/schemas/json/`)
can replace YOLO, PaddleOCR or the OpenCV stage without touching fusion or topology code.

## Layout

```
vision_pipeline/
  config/       settings.py (paths, model + OpenCV params)  thresholds.py (EVERY fusion threshold/weight)
  schemas/      raw.py (typed raw documents)  json/*.schema.json (JSON Schemas of the raw files + topology)
  yolo/         detector.py            image -> raw_yolo.json          (devices only)
  ocr/          detector.py            image -> raw_ocr.json           (text only, PaddleOCR)
                semantic_parser.py     text  -> device_name|ipv4|ipv4_cidr|subnet_mask|ipv6|ipv6_cidr|host_suffix|unknown
                address_normalizer.py  exact IPv4 / IPv6 / mask / prefix / network / host-suffix arithmetic
  opencv/       preprocessing.py  line_detector.py  segment_merger.py  path_reconstructor.py
                link_detector.py       image -> raw_opencv.json        (cable candidates, geometry only)
  fusion/       coordinate_normalizer  ocr_grouper  spatial_matcher  endpoint_matcher
                network_label_matcher  address_resolver  confidence  models  fusion_engine
  topology/     graph_builder.py (pass 10)   topology_builder.py (the ONLY writer of topology.json)
  validation/   validator.py (pre-RAG checks)  corrections.py (user fixes)  autoaddress.py (VLSM plan)
                segments.py (broadcast segments through switches)  addressing.py (IPv4/IPv6 arithmetic)
  pipeline.py   orchestration only          cli.py  __main__.py
tests/          A-H addressing patterns, unit, architecture (import rules), fuzz, end-to-end
examples/       synthetic_demo.py
models/yolo/    put best.pt here
outputs/        generated JSON
docs/PIPELINE.md   full reference: schemas, scoring formulas, limitations
```

See [docs/PIPELINE.md](docs/PIPELINE.md) for the schemas, every scoring formula and the known limitations.
