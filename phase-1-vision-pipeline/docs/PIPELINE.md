# Pipeline reference

All numbers below are the **defaults** in `vision_pipeline/config/thresholds.py` /
`settings.py`; every one can be overridden from a YAML/JSON config (`--config`). Inspect the
effective values with `python -m vision_pipeline print-config`.

## 1. Execution flow

```
image --+--> YOLO      --> raw_yolo.json  --+
        +--> PaddleOCR --> raw_ocr.json   --+--> [fusion reads the 3 files back from disk]
        +--> OpenCV*   --> raw_opencv.json -+
                                            v
   1 coordinate normalisation   6 host-suffix -> device       10 graph reconstruction
   2 OCR semantic classification 7 cable endpoint -> device      v
   3 OCR grouping                8 network label -> link       fusion.json
   4 device-name association     9 Address Resolver               v
   5 direct address association                              Topology Builder --> topology.json
                                                                              --> topology.simple.json (RAG input)
                                                                                   v
                                         validation.json <-- Validator <---------+
                                               |                                  ^
                                               +--> user: correct (checked) ------+
                                               +--> or autoaddress (VLSM plan) ---+   until valid
```
\* OpenCV optionally masks device interiors / text using raw_yolo / raw_ocr rectangles, so it runs after them.

## 2. Raw schemas (JSON Schema files in `vision_pipeline/schemas/json/`)

Every document has `schema_version`, `coordinate_system: "original_image_pixels"`, `image {path,width,height}`, `producer {...}`.

**raw_yolo.json** - `detections[]`: `{id: "device_001", class, confidence, bbox: [x1,y1,x2,y2], center: [cx,cy]}`.
`class` is whatever the model reports; the full list is in `producer.class_names` (and top-level `class_names`).
IDs are assigned in reading order (top-to-bottom, left-to-right, row-banded).

**raw_ocr.json** - `texts[]`: `{id: "text_001", text, confidence, bbox, center, polygon | null}`. Verbatim strings, no semantics.

**raw_opencv.json** - `link_candidates[]`:
```
{id: "link_candidate_001", segments: [{p1,p2}...], polyline: [[x,y]...],
 path_type: single | chain | branched | cycle,
 start: [x,y] | null, end: [x,y] | null, endpoints: [[x,y]...],
 confidence, quality: {ink_support, observed_fraction, length_score, endpoint_score, length_px}}
```
`start`/`end` are `null` for `branched` and `cycle` paths (no well-defined endpoints); leaf points are still listed in `endpoints`.
Plus `stats` (segment counts after each stage).

**fusion.json** (debugging/traceability, not RAG-oriented): `raw_references`, `warnings`,
`ocr_classifications` (raw + normalised text, semantic type, semantic/OCR confidence, bbox, parsed address),
`ocr_groups` (members, pairwise score parts, grouping confidence), `ocr_group_placements`,
`device_name_associations`, `address_associations`, `direct_address_bindings`, `host_suffix_associations`
(each with status, final confidence, flags and the full spatial score breakdown incl. runner-up),
`cable_candidates` (kept/unresolved + reason), `cable_endpoint_associations`, `network_label_associations`,
`resolved_addresses` (status, reason, address, combined confidence, provenance with per-component confidences),
`ambiguous`, `unresolved`, `graph` (nodes/edges of pass 10), `config.thresholds` (the values actually used).

**topology.json**
```
{ schema_version, metadata {image, width, height, pipeline_version, source},
  devices [ {id, type, name|null,
             network {ip_address, prefix_length, subnet_mask, network_address, host_suffix},   # each nullable
             addresses [ {link_id|null, ip_address, prefix_length, subnet_mask, network_address, host_suffix,
                          source: ocr_direct | host_suffix_resolution | host_suffix_only,
                          confidence, flags, unresolved_reason, provenance {field: {method, sources, evidence}}} ],
             confidence {device_detection, name, network_information, overall},
             flags, provenance} ],
  links   [ {id, source, target|null, network {network_address, prefix_length, subnet_mask},
             confidence {cable_detection, source_endpoint, target_endpoint, network_label, overall},
             flags, provenance} ],
  unresolved [ {kind, reason, ...evidence} ] }
```
Differences from the sketch in the task, all deliberate:
* `addresses[]` was added: a router with two subnets has two addresses and a scalar block cannot hold both.
  The scalar `network` block mirrors the device's address **only when it has exactly one**; with zero or several it is all-null
  (choosing one would be a guess). Consumers that need every address read `addresses`.
* link `confidence` is an object (cable / each endpoint / network label / overall) instead of one number, so the separate
  confidences the model requires are not collapsed. `overall` is the number in the sketch.
* `unresolved` holds only network-relevant leftovers (names, addresses, masks, suffixes, network labels, rejected link candidates).
  Unclassified text ("Figure 1") is kept in `fusion.json` only.

### topology.simple.json (the RAG input)

Written by `TopologyBuilder.build_simple()` from `topology.json` - a projection, nothing is added:
```
{ "devices": [ {"id": "device_1", "type": "router", "name": "R1",
                "network":  {"ip_address", "prefix_length", "subnet_mask", "network_address"},
                "network6": {"ip_address", "prefix_length", "network_address"}} ],          <- only with IPv6
  "links":   [ {"id": "link_1", "source": "device_1", "target": "device_2" | null,
                "network":  {"network_address", "prefix_length", "subnet_mask", "source_ip", "target_ip"},
                "network6": {"network_address", "prefix_length", "source_ip", "target_ip"}} ] }  <- only with IPv6
```
* `source_ip` / `target_ip` = the address each end uses on that link (null at a switch end, or when unknown). A router joining
  two subnets has a different one on each link; its own `network` is the address on its first link.
* A cable with no label takes the one network its known end addresses agree on; otherwise it stays null.
* `network6` has no subnet mask (IPv6 uses the prefix only, 0-128). It appears only when IPv6 was detected, so IPv4-only output is unchanged.
* ids drop the zero padding (`device_001` -> `device_1`); links reference the shortened device ids.
* `type` goes through `device_type_aliases` (default `{"desktop": "pc"}`), applied here only; `topology.json` keeps the model's class name.
* No `host_suffix`, confidence, provenance, flags or `unresolved`.
* A device with no address has an all-null `network`; `topology.json` `addresses[]` keeps every address it has.
* Schema: `schemas/json/topology_simple.schema.json`.

## 3. OCR semantic classification (`ocr/semantic_parser.py`)

Text is NFKC-normalised, trimmed, whitespace-collapsed (the original is kept in `raw_text`). Then, first match wins:
1. `ipv4_cidr` - `a.b.c.d/n`, octets 0-255 without leading zeros, n 0-32. Host form or network form (below).
2. dotted quad -> strict IPv4; if it is a *contiguous* mask (`inverted & (inverted+1) == 0`, not `0.0.0.0`) -> `subnet_mask`
   (+ prefix), else `ipv4`. `255.255.255.0` -> mask /24; `192.168.1.1`, `255.0.255.0` -> ipv4; `0.0.0.0` -> unknown.
3. `host_suffix` - `.N`, N in 0..255 (IPv4), or `::N`, N = 1-4 hex digits (IPv6, the host part alone).
3b. `ipv6_cidr` / `ipv6` - strict IPv6 (`2001:db8::1/64`, `fe80::1`), stored lowercase and compressed (`2001:DB8:0::1` -> `2001:db8::1`).
   Rejected: zone ids (`fe80::1%eth0`), `::` alone, `:::`, groups longer than 4 hex digits, prefix > 128 or with a leading zero.
   An IPv6 network form is a prefix <= 126 with zero host bits (`2001:db8:1::/64`).
4. `device_name` - `^[A-Za-z]{1,12}[-_]?\d{1,4}$` (R1, PC1, SW-2, Router10). Overridable via `device_name_pattern`.
5. otherwise `unknown` - never forced.

Labels such as `IPv6:`, `IPv4:`, `Subnet:`, `GW:` in front of an address are removed.
Two flagged repairs (lower the semantic confidence): whitespace touching `.` or `/` is removed (`192.168. 1.1`); a region holding several
tokens is split **only if every token classifies** (`R1 192.168.1.1`), with sub-boxes proportional to character offsets.
Semantic confidence: ipv4/cidr/mask 1.0, host_suffix 0.95, device_name 0.90; x0.9 per repair.

A CIDR whose address equals its network address with prefix <= 30 is **network form** (`192.168.1.0/24`): mathematically
not a host, so it is never grouped with a name and never attached to a device - only considered as a link label.

## 4. OCR grouping (`fusion/ocr_grouper.py`)

Groupable: `device_name`, `ip` (ipv4, host-form CIDR), `subnet_mask`. Never grouped: suffixes, unknown text, network-form CIDR.
Pair score = 0.40 distance + 0.30 alignment + 0.10 reading order + 0.20 semantic compatibility, where
distance = `1 - gap / (2.0 x text height)` (gap = bbox-to-bbox), alignment = best of centre/left/right offset for stacked
texts (vertical offset for same-line texts) relative to 0.6 x the larger extent, reading order = name -> ip -> mask -> ip6
top-to-bottom / left-to-right (else 0.6), compatibility name|ip 1.0, ip|mask 1.0, name|mask 0.6, name|ip6 1.0, ip|ip6 0.9,
mask|ip6 0.8, others 0. A dual-stack label (name / IPv4 / IPv6 lines) is one group and gives the device one address of each family.
Greedy merge by descending score if score >= 0.60, the group stays legal (one name, one ip, one mask; a CIDR excludes a
separate mask) and **no competing partner of the same kind scores within 0.08** - then both stay independent.
Group confidence = mean of the merging edge scores. Independent texts are judged on their own in the next passes.

## 5. Text -> device scoring (passes 4, 5, 6; `fusion/spatial_matcher.py`)

Per (text-or-group rectangle, device): candidates need `gap <= max_gap_factor x device size` (name 0.6, address 0.9,
suffix 0.9, group 0.8). Score = 0.35 gap + 0.10 centre + 0.10 location + 0.20 alignment + 0.15 OCR conf + 0.10 YOLO conf:
gap = `1 - gap/limit`; centre = `1 - centre distance / (2 x size)`; location: below 1.0, above 0.9, right/left 0.85, inside 0.7,
diagonal 0.6; alignment = centred-ness on the axis perpendicular to the side the text sits on. All distances are divided by
the device size (resolution independent). A group is placed as a whole first (union box); its members inherit the device with
confidence `geo_mean(group placement, group confidence, semantic)`. If the group cannot be placed, members are scored individually.
Name conflicts: two names claiming one device within 0.08 -> both refused; otherwise the higher wins, the other is unresolved.

## 6. Cable endpoint -> device (pass 7; `fusion/endpoint_matcher.py`)

Per (endpoint, device), candidates within `0.6 x size` of the bbox: 0.45 proximity (`1 - d/limit`) + 0.30 direction (the cable
extended past its end along its final direction enters the device within 1.0 x size: geometric continuity) + 0.10 intersection
(terminal segment enters the bbox) + 0.15 YOLO conf. `null` endpoints are never matched. Link kept if at least one endpoint is
matched, the endpoints are different devices, the path is not `branched`/`cycle`, and geometric confidence >= 0.30; otherwise the
candidate goes to `unresolved` with a reason. One matched endpoint -> `source` = that device, `target` = `null`.
Two matched -> ordered by device id (links are undirected).

## 7. Network label -> link (pass 8; `fusion/network_label_matcher.py`)

Only network-form CIDR texts. Per (label, link), within 3 text-heights of the path: 0.40 distance + 0.15 alignment
(70% "beside the cable body, not beyond an end", 30% label/cable parallelism) + 0.15 midpoint (label to the cable's arc-length
midpoint) + 0.15 device-relative (`1 - 2 x d_link/(d_link + d_nearest_device)`: a label nearer a device than the cable is not a cable
label) + 0.15 OCR conf. Two different labels of the same family claiming one link -> neither is applied (one IPv4 and one IPv6 label
on a dual-stack cable are both kept). Unapplied labels go to `unresolved`.

## 8. Host-suffix resolution (pass 9; `fusion/address_resolver.py`)

1. The suffix is already attached to a device (pass 6). Among the links ending at that device choose the one scoring best on
   0.6 path distance (within 4 text-heights) + 0.4 distance to the cable end at the device (within 1.5 device sizes); ties -> ambiguous.
   Chosen among **all** the device's links, so the suffix is never moved to another cable because that one has a label.
2. The link needs an applied network label, else `link_has_no_network_label` (suffix kept, everything else null).
3. Arithmetic: `candidate = (network_int & 0xFFFFFF00) | suffix`, only for prefix /24../31; verified inside the network and not
   the network/broadcast address (<= /30). `10.10.0.0/16 + .20`, `10.0.0.4/30 + .1` -> unresolved with a reason.
   IPv6: `::N` is the whole host part, `candidate = network_int | N`, any prefix up to /127 as long as N fits in the host bits
   (`2001:db8:1::/64 + ::2` -> `2001:db8:1::2`). A `.N` suffix only uses the link's IPv4 label, a `::N` suffix only its IPv6 label.
4. Combined confidence = geometric mean(OCR, semantic, suffix->device, suffix->link, endpoint->device, label->link, cable) must be >= 0.55 (>= 0.75
   accepted, otherwise flagged `low_confidence`).
5. Consistency: two different suffixes for one (device, link), or the same address for different devices on a link -> all cancelled.

## 9. Address normalisation (`ocr/address_normalizer.py`)

* CIDR `a.b.c.d/n`: ip, prefix n, mask = `(0xFFFFFFFF << (32-n)) & 0xFFFFFFFF`, network = `ip & mask`. Mask and network are marked `derived_from_*`.
* IP + dotted mask: mask must be contiguous; prefix = `32 - bit_length(~mask & 0xFFFFFFFF)`; network = `ip & mask`.
* IP only: prefix / mask / network stay null (no `/24` assumption, ever). Mask only: mask + prefix kept, ip / network null.
* A stray mask and a stray prefix-less IP attached to the same device are paired only when there is exactly one of each.
* Direct addresses are not tied to a link (`link_id: null`).
* IPv6: no mask exists (`subnet_mask: null`); the network is the address with its host bits cleared. A mask is never paired with an IPv6 address.

## 10. Confidence model

Tiers (per association, `TierThresholds`): `>= 0.75` accepted; `0.55-0.75` accepted + `low_confidence` flag; `< 0.55` unresolved (null,
evidence kept); runner-up >= 0.55 and within 0.08 of the winner -> ambiguous (null, both candidates recorded).
Separate values are kept for: YOLO detection, OCR recognition, semantic classification, group construction, text->device, suffix->device,
cable detection (`0.4 ink support + 0.2 length + 0.2 observed fraction + 0.2 endpoints`), endpoint->device, label->link, resolved IP
(geometric mean of the chain), final device, final link. Chains of evidence are combined with a **geometric mean** so one weak link drags the
whole chain down. Device `overall` = geometric mean of the *present* components (detection, name, network information); a missing name is `null`,
not a penalty. Link `overall` = geometric mean(cable, endpoints) x 0.6 per missing endpoint.

## 11. Missing / ambiguous data

Scalars `null`, collections `[]`. No fabricated provenance: provenance entries exist only for values that exist. Nothing is dropped silently:
every text or cable candidate that was not used appears in `unresolved` (topology) / fusion.json with a `reason`
(`no_device_nearby`, `ambiguous_device_association`, `association_confidence_below_threshold`, `no_link_nearby`,
`link_has_no_network_label`, `prefix_outside_final_octet_range`, `no_device_at_either_endpoint`, ...). `TopologyBuilder` validates the final document
(arithmetic consistency of ip/prefix/mask/network, ids, provenance for every ip) and raises instead of repairing.

## 12. Pre-RAG validation, corrections, auto-addressing (`validation/`)

Works only on `topology.simple.json` (the RAG contract), never on detector output.

**Validator** (`validate`, written to `validation.json`): `{valid, status, errors[], warnings[], segments[], summary}`. Each issue has
`code`, `severity`, `path` (JSON pointer, e.g. `/links/2/network/target_ip`), `message`, `subject` (device/link id), `value`, `related`
and sometimes `hint` (the expected value, a suggested prefix). It applies the RAG readiness rules with the same codes and paths
(`missing_*`, `invalid_ip_address`, `invalid_prefix_length`, `invalid_subnet_mask`, `subnet_mask_mismatch`, `network_address_mismatch`,
`invalid_network_address`, `unknown_device`, `self_link`, `missing_link_ip`, `invalid_link_ip`, `link_ip_outside_network`,
`isolated_device`, `too_many_links`, `device_ip_not_on_link`, ...), then adds:

| code | meaning |
|---|---|
| `duplicate_ip` | one address used by two devices (reported at every place it is used) |
| `ip_reused_on_several_links` | one device uses the same address on two segments |
| `duplicate_device_name` | two devices with the same name (case-insensitive) |
| `ip_looks_like_mask` | a host IP that is a mask (`255.255.0.0`): the mask was read as the IP |
| `reserved_ip` | 0.0.0.0/8, loopback, multicast, 240.0.0.0/4, `::`, `::1`, `ff00::/8` |
| `ip_is_network_address` / `ip_is_broadcast_address` | IPv4 (prefix <= 30) network / broadcast, IPv6 subnet-router anycast (prefix <= 126) |
| `segment_network_mismatch` | links joined by a switch carry different networks |
| `overlapping_networks` | two segments share or overlap a network |
| `network_too_small` | a segment's network has fewer usable addresses than devices; `hint.suggested_prefix` gives the VLSM fit |
| `unexpected_subnet_mask` | a mask in an IPv6 block |
| warnings: `non_canonical_ip`, `link_local_ip`, `layer2_device_routes` | reported, do not block |

*Segments*: links joined by a switch/bridge/hub are one broadcast segment. A switch with a management IP counts as a host on it.
A switch whose own addresses are in two or more networks is routing (layer-3 switch), so it only joins links that carry the same network.
Usable addresses: IPv4 `2^h - 2` (/31 = 2, /32 = 1); IPv6 `2^h - 1` (/127 = 2, /128 = 1).
`require_ipv4=True` (default, same as the RAG) needs IPv4 on every non-L2 device; `--allow-ipv6-only` accepts IPv6 alone.

**Corrections** (`correct`, `validation.corrections.apply_corrections`): a JSON list, applied in order, each applied fully or rejected with a code:
`{"device", "ip"[, "prefix" | "mask"][, "link"]}`, `{"link", "network"}`, `{"device", "name"}`, `{"device", "type"}`. The family follows from the value.
A missing prefix comes from the link; the new address replaces the old one on the device and on the link ends that carried it.
Rejected: malformed input, non-contiguous or mismatched mask, mask on IPv6, prefix out of range, a mask / reserved / network / broadcast
address as a host, an address another device uses, an address outside the link's network, host bits in a network, empty or duplicate name.
The detected file is kept once as `topology.simple.detected.json`.

**Auto-addressing** (`autoaddress`): recomputes every address from the graph. One network per segment, sized to fit (IPv4 smallest block,
at least /30; IPv6 /64, or sized like IPv4 with `--ipv6-vlsm`). Placed largest first, aligned, packed inside the base (default `192.168.0.0/16`,
IPv6 `2001:db8::/48` when the topology has IPv6), so blocks never overlap; a base that is too small is refused. The router (then firewall,
server, switch) gets the first usable address. Writes `addressing_plan.json`. Example: LANs of 50, 20 and 5 PCs plus two router links in
`172.16.0.0/24` -> `.0/26`, `.64/27`, `.96/29`, `.104/30`, `.108/30`.

## 13. Known limitations

* **Real-model verification is partial.** Verified with real libraries (Python 3.13, ultralytics 8.4.157, paddleocr 3.7.0 / paddlepaddle 3.3.1): the
  YOLO adapter loads the supplied `best.pt` (classes `desktop, firewall, router, server, switch`) and runs; the PaddleOCR adapter reads a synthetic
  diagram; the OCR -> OpenCV -> fusion -> topology chain reproduces the expected topology. **Not** verified: YOLO detection quality on real diagrams
  (the synthetic image has no real device icons, so it returned 0 detections) - that needs real diagrams.
* **Thresholds are hand-set**, not calibrated on real diagrams. Tune them in the config using `fusion.json` (it records every score component).
* PaddleOCR often drops tiny text such as `.1`; a missed suffix means that address stays `null`. `ocr.upscale` (e.g. 2.0) can help.
* Cables: T-junction / bus / hub drawings become `branched` candidates with `null` endpoints and are **not** turned into links. Curved, dashed
  (gap > 20 px) or arrow-headed cables and busy backgrounds are not specially handled. Without raw_yolo masking, cables docking on one device can merge.
* Switch transitivity is not inferred: a host behind a switch whose link has no label stays `null`, by design.
* The RAG readiness check is IPv4-only (prefix 0-32): it ignores `network6`. IPv6 is checked here, by the validator.
* Suffix notation: `.N` as the final octet with prefix /24../31, or `::N` as the IPv6 host part. Network labels only as CIDR with zero host bits (`192.168.1.0/24`); a plain
  `192.168.1.0` + separate mask on a link is not recognised. Interface names, VLANs, routes, ACLs are out of scope (a token like `Fa0` matches the device-name
  pattern - override `device_name_pattern` if such labels appear).
* Device names must fit the name pattern; free text ("Core Router") is `unknown` -> `name: null`.
* Multi-homed devices: in `topology.json` the scalar `network` block is null, use `addresses`. Direct (OCR) addresses are not tied to a link.
* Rotated text uses axis-aligned boxes (angle only from the OCR polygon).
