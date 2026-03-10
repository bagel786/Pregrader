# Pregrader Grading Model — Technical Reference

This document describes the complete grading pipeline: how a card image becomes a PSA-aligned numeric grade, including every formula, threshold, weight, and blending decision.

---

## Table of Contents

1. [Pipeline Overview](#1-pipeline-overview)
2. [Card Detection & Perspective Correction](#2-card-detection--perspective-correction)
3. [Centering Analysis](#3-centering-analysis)
4. [Corners Analysis](#4-corners-analysis)
5. [Edges Analysis](#5-edges-analysis)
6. [Surface Analysis](#6-surface-analysis)
7. [Final Score Calculation](#7-final-score-calculation)
8. [Front + Back Blending](#8-front--back-blending)
9. [Confidence System](#9-confidence-system)
10. [Claude Vision API Integration](#10-claude-vision-api-integration)
11. [API Session Flow](#11-api-session-flow)
12. [Constants Reference](#12-constants-reference)

---

## 1. Pipeline Overview

```
User uploads front image
         │
         ▼
  Card Detection (OpenCV → Claude Vision fallback)
         │
         ▼
  Perspective Correction  (500×700 px canonical)
         │
         ├──► Centering Analysis
         ├──► Corners Analysis  (basic + enhanced)
         ├──► Edges Analysis
         └──► Surface Analysis
                    │
                    ▼
         User uploads back image (optional)
                    │
         (same detection + 4 analyses)
                    │
                    ▼
         Front + Back Blending
                    │
                    ▼
         Weighted Score Calculation
                    │
                    ▼
         Damage Penalty Application
                    │
                    ▼
         PSA Grade Bracket Lookup
```

All analysis runs on the perspective-corrected, cropped card image — never on the raw photo.

---

## 2. Card Detection & Perspective Correction

**File:** `backend/api/hybrid_detect.py`, `backend/services/ai/vision_detector.py`

### 2.1 OpenCV Detection (Primary Path)

Four independent methods run on the uploaded image. The highest-scoring result wins if it clears the confidence threshold.

| Method | Preprocessing | Edge Algorithm |
|--------|--------------|----------------|
| Standard | CLAHE → GaussianBlur 5×5 | Canny(50, 150) |
| Adaptive | CLAHE → GaussianBlur 5×5 | adaptiveThreshold(blockSize=11, C=2) |
| Morphological | CLAHE → GaussianBlur 5×5 | Canny(50, 150) + morphClose(3×3, iter=2) |
| LAB | CLAHE on L-channel → GaussianBlur 5×5 | Canny(30, 90) — lower thresholds for low light |

**Contour Scoring:**

```
valid contour IF:
    area ∈ [0.20 × image_area, 0.90 × image_area]
    aspect_diff = min(|aspect - 0.714|, |aspect - 1.4|) ≤ 0.08

score = (area / image_area) × (1 - aspect_diff)
```

The target aspect ratio of 0.714 (500/700) matches a standard Pokemon card.

**Acceptance Threshold:** `confidence ≥ 0.70`

If none of the four methods reaches 0.70, the system falls back to Claude Vision.

### 2.2 Perspective Correction

Once 4 corners are found (by either OpenCV or Claude Vision), a perspective transform maps the card to a canonical 500×700 px rectangle:

```
dst_pts = [[0,0], [499,0], [499,699], [0,699]]
M = cv2.getPerspectiveTransform(src_corners, dst_pts)
corrected = cv2.warpPerspective(image, M, (500, 700))
```

All subsequent analysis runs on this corrected image.

---

## 3. Centering Analysis

**File:** `backend/analysis/centering.py`

Centering measures how evenly the card artwork is positioned within the border. It contributes **20%** of the final weighted score.

### 3.1 Border Detection (Fallback Chain)

Three methods attempt border measurement in order of preference:

**Method 1: Artwork Box Detection (confidence 0.9)**

Find the largest bounding contour that:
- Has area between 15% and 70% of card area
- Has aspect ratio 0.5–2.0
- Is not trivially close to the corner

**Method 2: Gradient-Based Detection (confidence 0.8)** — most commonly used

```
FOR threshold in [35, 40, 45]:
    grad_x = |Sobel_X(gray, ksize=3)|
    grad_y = |Sobel_Y(gray, ksize=3)|

    FOR x from min_border to min(width/4, 150):
        IF mean(strong_x[:, x]) > 30:
            left_width[run] = x
            break

    (same for right, top, bottom)

border = median of 3 threshold runs  # stability
```

Minimum enforced borders prevent artifacts:
```
min_border_w = max(1px, width × 0.02)
min_border_h = max(1px, height × 0.02)
```

Symmetry correction prevents pathological asymmetry:
```
IF left_width < width×0.05 AND right_width > left_width × 3:
    left_width = max(left_width, width × 0.10)
```

**Method 3: Saturation-Based Detection (confidence 0.7)** — legacy fallback

Scans inward from each edge until a saturated (>60 saturation value) column is found.

### 3.2 Centering Score Calculation

```
lr_ratio = min(left, right) / max(left, right)
tb_ratio = min(top, bottom) / max(top, bottom)
avg_ratio = (lr_ratio + tb_ratio) / 2
```

| avg_ratio range | Score formula |
|-----------------|--------------|
| ≥ 0.975 | 10.0 |
| 0.950–0.975 | 9.0 + (ratio − 0.95) / 0.025 |
| 0.900–0.950 | 8.0 + (ratio − 0.90) / 0.05 |
| 0.850–0.900 | 7.0 + (ratio − 0.85) / 0.05 |
| 0.750–0.850 | 6.0 + (ratio − 0.75) / 0.10 *(dampened)* |
| 0.600–0.750 | 5.0 + (ratio − 0.60) / 0.15 *(dampened)* |
| 0.450–0.600 | 4.0 + (ratio − 0.45) / 0.15 |
| < 0.450 | max(2.0, 4.0 × ratio / 0.45) |

The dampened ranges (0.60–0.85) have wider bands, reducing sensitivity to measurement noise in mid-range cards.

**Fallback:** If `lr_ratio < 0.3 OR tb_ratio < 0.3`, the measurement is considered unreliable and a conservative default of `5.0` is used with `confidence = 0.5`.

---

## 4. Corners Analysis

**Files:** `backend/analysis/corners.py`, `backend/analysis/enhanced_corners.py`

Corners detect whitening — the paper substrate showing through worn corner tips. Corners contribute **30%** of the final weighted score.

### 4.1 Basic Corner Analysis (`corners.py`)

#### ROI Extraction

```
roi_size = max(30px, int(min(height, width) × 0.04))
```

Each corner ROI is positioned *inside* the card (not centered on the corner point). The ROI is masked against the card boundary, and at least **17% of the ROI must be on-card** to be considered valid. If ROI coverage is below 50%, the whitening percentage is scaled down proportionally.

#### Whitening Detection (Adaptive, Color-Agnostic)

Uses LAB + HSV to detect paper white regardless of card color:

```
lightness_threshold = median_L + 45
saturation_threshold = max(median_S × 0.5, 30)

whitened_pixels = pixels WHERE (L > lightness_threshold) AND (S < saturation_threshold)
whitening_pct = (whitened_pixels / total_pixels) × 100
```

#### Corner Score Mapping (linear interpolation between anchors)

| Whitening % | Score |
|-------------|-------|
| 0.0 | 10.0 |
| 0.5 | 10.0 |
| 1.5 | 9.5 |
| 3.0 | 9.0 |
| 5.0 | 8.5 |
| 8.0 | 8.0 |
| 12.0 | 7.0 |
| 18.0 | 6.0 |
| 25.0 | 5.0 |
| 35.0 | 4.0 |
| 50.0 | 2.0 |
| ∞ | 1.0 |

Values between anchors are linearly interpolated.

#### Overall Corner Grade

```
avg_score = mean(4 corner scores)
worst_corner = min(4 corner scores)

IF worst_corner < 6.0:
    penalty = (6.0 - worst_corner) × 0.5   # severe damage
ELIF worst_corner < 8.0:
    penalty = (8.0 - worst_corner) × 0.3   # moderate damage
ELSE:
    penalty = 0

overall_grade = max(avg_score - penalty, worst_corner)
```

#### Confidence

```
fallback_count = corners that failed ROI extraction

IF fallback_count ≥ 3:  confidence = 0.3
IF fallback_count ≥ 1:  confidence = 0.5
IF any_corner_had_issues: confidence = 0.6
ELSE:                   confidence = 1.0
```

### 4.2 Enhanced Corner Analysis (`enhanced_corners.py`)

Enhanced corners run a **false positive filtering pipeline** on top of basic detection.

#### Step 1: Image Validation

```
aspect = width / height
valid IF 0.6 < aspect < 0.85  (portrait)
      OR 1.18 < aspect < 1.67 (landscape)
```

Fails with confidence = 0.3 if invalid — this triggers the gating check in `main.py`.

#### Step 2: Card Region Mask

```
initial_mask = 5% inset from all edges
Refine using Canny(50, 150)
Largest contour must be > 50% of image area
Light erode (1 iteration) to remove edge artifacts
```

#### Step 3: Corner ROI with Validity Check

```
corner_size = int(min(height, width) × 0.08)
validity_ratio = on_card_pixels / corner_size²
valid IF validity_ratio > 0.2  (20% minimum on-card)
```

#### Step 4: False Positive Detection (4 checks per corner)

```python
white_mask = HSV inRange([0,0,180], [180,40,255])
white_pct = white_pixels / valid_area × 100

check_1_edge_whitening():
    IF >70% of damage concentrated at ROI edge → likely background bleed
    → is_false_positive = True

check_2_uniformity():
    IF large uniform blob > 30% of ROI → likely glare or plain border
    → is_false_positive = True

check_3_brightness():
    IF avg_brightness of white pixels > 240 → likely specular glare
    → is_false_positive = True

check_4_corner_zone():
    zone_mask = outer 40% of ROI
    IF < 60% of detected damage is in zone → damage not in corner position
    → is_false_positive = True
```

If any check triggers:

```
score = min(10.0, score + 2.0)   # adjust score upward
false_positives_filtered += 1
```

#### Enhanced Corner Score Mapping

| Whitening % | Score |
|-------------|-------|
| < 0.5 | 10.0 |
| 0.5–1.5 | 10.0 − (pct − 0.5) × 0.5 |
| 1.5–3.0 | 9.5 − (pct − 1.5) × (0.5/1.5) |
| 3.0–6.0 | 9.0 − (pct − 3.0) × (1.0/3.0) |
| 6.0–12.0 | 8.0 − (pct − 6.0) × (1.0/6.0) |
| 12.0–20.0 | 7.0 − (pct − 12.0) × (1.0/8.0) |
| 20.0–35.0 | 6.0 − (pct − 20.0) × (2.0/15.0) |
| 35.0–50.0 | 4.0 − (pct − 35.0) × (2.0/15.0) |
| ≥ 50.0 | max(1.0, 2.0 − (pct − 50.0) × 0.02) |

#### Enhanced Overall Grade

```
overall = (0.7 × avg_score) + (0.3 × min_score)
```

#### Enhanced Confidence

```
base_confidence = 0.9
confidence -= false_positives × 0.1

IF std(all_corner_scores) > 2.0:
    confidence -= 0.1

confidence = clamp(confidence, 0.3, 1.0)
```

### 4.3 Enhanced Corners Gating (in `main.py`)

Enhanced corners override basic corners only when reliable:

```python
IF enhanced_corners_available AND enhanced_confidence >= 0.5:
    side_analysis["corners"] = enhanced_result
ELSE:
    keep basic corners   # enhanced failed or low-confidence
```

The threshold was lowered from 0.7 to 0.5 after a bug was found where enhanced corners unconditionally replaced basic corners even when the card shape validation had failed (returning confidence = 0.3).

---

## 5. Edges Analysis

**File:** `backend/analysis/edges.py`

Edges detect whitening/wear along all four borders of the card. Edges contribute **30%** of the final weighted score.

### 5.1 Card Side Detection

```
blue_pct = pixels in HSV([90-140], [50-255], [30-255]) / total
yellow_pct = pixels in HSV([20-40], [80-255], [100-255]) / total

IF blue_pct > 40% AND yellow_pct < 5%:
    side = "back", confidence = min(1.0, blue_pct / 60)
ELIF blue_pct < 20%:
    side = "front", confidence = min(1.0, (100 - blue_pct) / 80)
ELSE:
    side = "front", confidence = 0.6
```

### 5.2 Border Mask Extraction

```
border_thickness = max(15px, int(min(height, width) × 0.03))
kernel = MORPH_RECT(border_thickness, border_thickness)
inner_mask = erode(card_mask, kernel, iterations=1)
border_mask = card_mask − inner_mask
```

Edge splits for per-edge analysis:
- Top: top 20% of image height
- Bottom: bottom 20% of image height
- Left: left 20% of image width
- Right: right 20% of image width

### 5.3 Whitening Detection

**Front cards (adaptive, works for any border color):**

```
avg_L = mean(L_channel in border_mask)
adaptive_threshold = avg_L + 35

whitened = pixels WHERE L > adaptive_threshold
whitening_pct = whitened / border_pixels × 100
```

**Back cards (fixed threshold for blue backs):**

```
WHITENING_THRESHOLD = 155  (LAB L-channel)
whitened = pixels WHERE L > 155
whitening_pct = whitened / region_pixels × 100
```

### 5.4 Edge Score Mapping

| Whitening % | Score |
|-------------|-------|
| < 0.2 | 10.0 (Gem Mint) |
| < 0.5 | 9.5 |
| < 1.0 | 9.0 (Mint) |
| < 1.5 | 8.5 |
| < 2.5 | 8.0 (NM-MT) |
| < 4.0 | 7.0 |
| < 6.0 | 6.0 |
| < 8.0 | 5.0 |
| < 12.0 | 4.0 |
| < 18.0 | 3.0 |
| ≥ 18.0 | max(1.0, 3.0 − (pct − 18.0) / 10.0) |

### 5.5 Final Edge Score

```
overall_whitening_score = score_mapping(total_whitening_pct)
worst_edge_score = min(top_score, bottom_score, left_score, right_score)

final_edges = (overall_whitening_score × 0.6) + (worst_edge_score × 0.4)
```

### 5.6 Confidence

```
IF total_border_pixels > 1000: confidence = 1.0
ELSE:                           confidence = 0.5

Special: IF contour covers >95% of image (full-frame fallback):
    confidence = 0.3
    use default score = 5.0
```

---

## 6. Surface Analysis

**File:** `backend/analysis/surface.py`

Surface detects scratches and major physical damage (creases, dents). Surface contributes **20%** of the final weighted score.

### 6.1 Glare Masking

```
HSV range: H[0-180], S[0-30], V[230-255]
kernel = 5×5 ones
glare_mask = dilate(raw_glare_mask, kernel, iterations=2)
```

Glare regions are excluded from scratch detection.

### 6.2 Holographic Region Detection

```
L_channel = LAB L
variance_map = blur(L²) − blur(L)²   (kernel=15)

holo_mask = variance_map > 120
holo_mask = morph_close(holo_mask, 7×7 ellipse)
holo_mask = morph_open(holo_mask, 7×7 ellipse)
```

High local variance in lightness identifies holographic patterns. These regions are excluded from scratch detection to prevent false positives on shiny/holographic cards.

### 6.3 Scratch Detection

```
enhanced = CLAHE(clipLimit=2.0, tileSize=8×8).apply(card_gray)
edges = Canny(enhanced, 120, 200)

vertical_lines = morph_open(edges, rect(1, 5))
horizontal_lines = morph_open(edges, rect(5, 1))
scratch_candidates = vertical_lines OR horizontal_lines

Exclude: glare_mask | holo_mask
```

**Filtering per contour:**

```
min_scratch_area = total_card_area × 0.0005   (0.05%)

FOR each contour:
    IF area < min_scratch_area: reject

    bounding_box = minAreaRect(contour)
    max_dim = max(bb.width, bb.height)
    min_dim = min(bb.width, bb.height)
    aspect = max_dim / min_dim

    IF aspect < 3.0: reject   (compact shape, not a scratch)
    ELSE: accept as scratch
```

### 6.4 Major Damage Detection (Creases/Dents)

```
dark_mask = threshold(card_gray, 25, 255, THRESH_BINARY_INV)
major_damage_threshold = total_card_area × 0.0015   (0.15%)

major_damage = contours WHERE area > major_damage_threshold
major_damage_detected = len(major_damage) > 0
```

### 6.5 Surface Score

| Scratch Count | Score |
|---------------|-------|
| 0 | 10.0 |
| 1–3 | 9.5 |
| 4–8 | 9.0 |
| 9–15 | 8.5 |
| 16–25 | 8.0 |
| 26–40 | 7.0 |
| 41–60 | 6.0 |
| 61–80 | 5.0 |
| 81+ | 4.0 |

```
IF major_damage_detected:
    score = min(score, 3.0)   # creases/dents cap score at 3
```

### 6.6 Confidence

```
obscured_pct = (glare_pixels + holo_pixels) / total_card_area × 100

IF obscured_pct > 40%: confidence = 0.60
IF obscured_pct > 25%: confidence = 0.70
IF obscured_pct > 15%: confidence = 0.85
ELSE:                   confidence = 1.00
```

---

## 7. Final Score Calculation

**File:** `backend/analysis/scoring.py`

### 7.1 Weighted Score

```
weighted_score = (centering × 0.20)
               + (corners   × 0.30)
               + (edges     × 0.30)
               + (surface   × 0.20)
```

### 7.2 Damage Penalties

Applied after the weighted score. Penalties are additive and capped at 2.5 total.

**Corner damage penalty** (based on the single worst corner score):

| Worst corner | Penalty | Rationale |
|-------------|---------|-----------|
| ≤ 2.5 | 1.5 | Destroyed corner |
| ≤ 4.0 | 0.8 | Severe damage, ~35%+ whitening |
| ≤ 5.5 | 0.3 | Significant damage, ~25%+ whitening |
| > 5.5 | 0 | No penalty |

**Surface damage penalty:**

```
IF major_damage_detected:
    penalty += 1.0
```

**Total penalty cap:**

```
total_damage_penalty = min(corner_penalty + surface_penalty, 2.5)
```

### 7.3 Final Score

```
final_score = weighted_score − total_damage_penalty
final_score = clamp(final_score, 1.0, 10.0)
final_score = round(final_score, 1 decimal place)
```

### 7.4 PSA Grade Brackets

| Score range | Grade | Label |
|-------------|-------|-------|
| ≥ 9.5 | 10 | Gem Mint |
| ≥ 9.0 | 9 | Near Mint |
| ≥ 8.0 | 8 | Excellent |
| ≥ 7.0 | 7 | Very Good |
| ≥ 6.0 | 6 | Good |
| ≥ 5.0 | 5 | Fair |
| ≥ 4.0 | 4 | Poor |
| ≥ 3.0 | 3 | Very Poor |
| ≥ 2.0 | 2 | Damaged |
| ≥ 1.0 | 1 | Heavily Damaged |
| < 1.0 | 0 | Ungradeable |

---

## 8. Front + Back Blending

**File:** `backend/api/combined_grading.py`

When the user uploads both sides, scores are combined with a worst-case bias (damaged side matters more).

### Centering

```
combined_centering = front_centering   # back centering is not meaningful
```

### Corners

```
front_avg = mean(front_corner_scores)
back_avg  = mean(back_corner_scores)
worse  = min(front_avg, back_avg)
better = max(front_avg, back_avg)

combined_corners = (worse × 0.55) + (better × 0.45)
```

### Edges

```
worse_edge  = min(front_edges, back_edges)
better_edge = max(front_edges, back_edges)

combined_edges = (worse_edge × 0.60) + (better_edge × 0.40)
```

### Surface

```
combined_surface = min(front_surface, back_surface)   # worst case only
```

The blended scores then feed into the standard weighted calculation.

---

## 9. Confidence System

**File:** `backend/analysis/scoring.py`

### Overall Confidence

```
overall_confidence = (centering_confidence × 0.20)
                   + (corners_confidence   × 0.30)
                   + (edges_confidence     × 0.30)
                   + (surface_confidence   × 0.20)
```

### Grading Status

| overall_confidence | Status | Meaning |
|--------------------|--------|---------|
| < 0.4 | `refused` | Image quality too low to grade |
| 0.4–0.6 | `low_confidence` | Grade provided but unreliable |
| ≥ 0.6 | `success` | Normal grading |

### Confidence Level Labels

| overall_confidence | Label |
|--------------------|-------|
| ≥ 0.8 | High |
| 0.6–0.8 | Medium |
| < 0.6 | Low |

---

## 10. Claude Vision API Integration

**File:** `backend/services/ai/vision_detector.py`

Claude Vision is used as a **fallback for card detection** when OpenCV confidence falls below 0.70. It is not used for the grading analysis itself — all scoring is performed by OpenCV-based algorithms.

### When It Activates

```
IF max(opencv_method_scores) < 0.70:
    fallback to Claude Vision API
```

### API Call

```
Model:   claude-sonnet-4-20250514
Tokens:  max 1024
Timeout: 10 seconds (configurable, default; hybrid_detect.py uses 30s)
```

The image is base64-encoded and sent as a multipart content message with the following prompt:

```
Analyze this image and detect if there's a Pokemon trading card present.

Your task:
1. Determine if a Pokemon card is visible
2. If yes, identify the 4 corner points of the card (top-left, top-right,
   bottom-right, bottom-left)
3. Assess image quality (lighting, blur, angle)
4. Provide confidence score

Respond in JSON format:
{
    "card_detected": true/false,
    "corners": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],
    "confidence": 0.0-1.0,
    "reasoning": "...",
    "card_type": "pokemon/other/none",
    "quality_assessment": {
        "lighting": "good/poor/glare",
        "blur": "sharp/slight/heavy",
        "angle": "straight/slight/heavy",
        "background": "plain/busy/unclear"
    }
}
```

Corner coordinates are in pixels relative to the original image dimensions.

### Response Parsing

Claude may wrap JSON in markdown code fences. Three extraction strategies are tried in order:

1. Extract from ` ```json ... ``` ` block
2. Extract from bare ` ``` ... ``` ` block
3. Extract first `{...}` JSON object from raw text

### Corner Refinement (Hybrid Step)

After Claude provides approximate corners, OpenCV refines each one:

```
FOR each AI corner (x, y):
    region = edges[y-50:y+50, x-50:x+50]   (search_radius=50px)

    IF edge_points found in region:
        best = edge_point closest to region center
        refined_corner = (x1 + best.x, y1 + best.y)
    ELSE:
        keep AI corner as-is
```

If refinement succeeds, confidence is boosted:

```
final_confidence = min(ai_confidence × 1.1, 1.0)
method = "ai_refined"
```

Otherwise:

```
final_confidence = ai_confidence
method = "ai_only"
```

### Configuration (Environment Variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Required for Vision API access |
| `OPENCV_CONFIDENCE_THRESHOLD` | 0.70 | Below this, use Claude Vision |
| `AI_TIMEOUT_SECONDS` | 30 | Max wait for Claude API response |
| `VISION_AI_PROVIDER` | "claude" | Vision provider (only Claude supported) |
| `MAX_CONCURRENT_AI_REQUESTS` | 5 | Concurrency limit for AI calls |

---

## 11. API Session Flow

**File:** `backend/main.py`

### Endpoints

```
POST   /api/grading/start
POST   /api/grading/{session_id}/upload-front
POST   /api/grading/{session_id}/upload-back
GET    /api/grading/{session_id}/result
DELETE /api/grading/{session_id}
```

### Upload Processing Steps

```
1. Size check: reject if > 15 MB
2. Image quality check (basic loadability)
3. Hybrid card detection (OpenCV → Claude Vision fallback)
4. Perspective correction → 500×700 px canonical image
5. Run 4 analyses: centering, corners, edges, surface
6. Attempt enhanced corners:
     IF enhanced_confidence >= 0.5:
         replace basic corners with enhanced result
7. Store analysis in session
8. (back upload only) Blend front + back → compute final grade
```

### Session Lifecycle

```
Session TTL:       15 minutes
Cleanup interval:  120 seconds (background task)
Cleanup action:    delete files + session dict entry + gc.collect()
```

### File Size & CORS

```
Max upload:     15 MB per image
Allowed origins:
  - https://pregrader-production.up.railway.app
  - http://localhost:8000
  - http://localhost:3000
```

---

## 12. Constants Reference

### Weights

| Component | Weight |
|-----------|--------|
| Centering | 0.20 |
| Corners | 0.30 |
| Edges | 0.30 |
| Surface | 0.20 |

### Damage Penalties

| Condition | Penalty |
|-----------|---------|
| worst_corner ≤ 2.5 | 1.5 |
| worst_corner ≤ 4.0 | 0.8 |
| worst_corner ≤ 5.5 | 0.3 |
| worst_corner > 5.5 | 0.0 |
| major_damage (crease/dent) | 1.0 |
| **cap** | 2.5 |

### Front + Back Blending

| Component | Worse side weight | Better side weight |
|-----------|------------------|--------------------|
| Corners | 0.55 | 0.45 |
| Edges | 0.60 | 0.40 |
| Surface | 1.00 (worst only) | — |

### ROI / Geometry

| Parameter | Value |
|-----------|-------|
| Corner ROI size | max(30px, min_dim × 0.04) |
| Enhanced corner ROI | min_dim × 0.08 |
| Edge border thickness | max(15px, min_dim × 0.03) |
| Edge region per side | 20% of dimension |

### Surface Detection

| Parameter | Value |
|-----------|-------|
| Min scratch area | total_area × 0.0005 |
| Major damage threshold | total_area × 0.0015 |
| Scratch aspect ratio min | 3.0 |
| Holo variance threshold | 120 |
| Glare brightness (V) | ≥ 230 |

### Enhanced Corners — False Positive Thresholds

| Check | Threshold |
|-------|-----------|
| Edge concentration | > 70% of damage at ROI edge |
| Uniform blob | > 30% of ROI |
| Glare brightness | avg_brightness > 240 |
| Corner zone depth | outer 40% of ROI |
| Corner zone concentration | < 60% in zone → FP |
| Min validity ratio | 0.2 (20% on-card) |

### Confidence Thresholds

| Context | Threshold | Action |
|---------|-----------|--------|
| OpenCV detection | ≥ 0.70 | Use OpenCV, skip Claude Vision |
| Enhanced corners gate | ≥ 0.50 | Use enhanced result |
| Grading refused | < 0.40 | Return refused status |
| Low confidence grading | 0.40–0.60 | Return grade with warning |
| AI timeout | 30 seconds | Raise TimeoutError |

---

*Generated from source code review — backend/analysis/, backend/api/, backend/services/ai/*
