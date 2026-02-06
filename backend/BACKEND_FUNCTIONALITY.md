# Backend Computer Vision Functionality

This document details the algorithms and logic used in the backend for Pokémon card analysis, specifically focusing on card detection, surface analysis (scratches), centering, and edge wear detection.

## 1. Image Card Finding & Detection

**Location:** `backend/analysis/vision/image_preprocessing.py`, `backend/analysis/utils.py`

The card detection system uses a robust, multi-stage approach to identify the card boundary within an uploaded image.

### Algorithm Steps:
1.  **Preprocessing:**
    *   **LAB Conversion:** The image is converted to LAB color space.
    *   **CLAHE:** Contrast Limited Adaptive Histogram Equalization is applied to the L-channel to enhance local contrast.
    *   **Denoising:** Bilateral filtering reduces noise while preserving edges.

2.  **Detection Methods (Robust Fallback System):**
    *   **Method A: Adaptive Canny Edges:**
        *   Calculates adaptive threshold values based on the median image intensity.
        *   Applies Canny edge detection.
        *   Uses morphological closing to connect broken edge lines.
    *   **Method B: Color Segmentation:**
        *   Uses K-means clustering (k=3) in LAB space to separate the card from the background.
        *   Identifies the cluster representing the card based on area and shape properties.
    *   **Method C: Full Frame Fallback:**
        *   If specific detection fails, the system checks if the image aspect ratio matches a standard card (approx 0.714).
        *   If within tolerance (0.60 - 0.85), it assumes the image is already cropped to the card.

3.  **Validation Criteria:** A contour is accepted as a card only if it meets:
    *   **Aspect Ratio:** ~0.60 to 0.85 (Target: 0.714).
    *   **Rectangularity:** Area / BoundingBoxArea > 0.85.
    *   **Solidity:** Area / ConvexHullArea > 0.90.
    *   **Area:** Covers 20% - 95% of the total image.

4.  **Perspective Correction:**
    *   Once detected, the 4 corners are extracted.
    *   A perspective transform (`cv2.warpPerspective`) is applied to "flatten" the card into a top-down view for further analysis.

---

## 2. Surface & Scratch Detection

**Location:** `backend/analysis/surface.py`

This module detects surface imperfections like scratches, creases, and dents.

### Algorithm Steps:
1.  **Glare Management:**
    *   Converts image to HSV to detect glare (high brightness/low saturation).
    *   Creates a `glare_mask` to ignore bright reflections that might mimic scratches.
    *   **Confidence Score:** Reduces grading confidence if glare covers >10% of the card.

2.  **Scratch Detection:**
    *   Applies CLAHE to enhance fine details.
    *   Uses Canny edge detection (thresholds 100, 200).
    *   **Directional Filtering:** Uses specific kernels to filter for *vertical* and *horizontal* lines, which are characteristic of scratches.
    *   Filters out contours with area < 20 pixels (noise).

3.  **Major Damage (Creases/Dents):**
    *   Thresholds the image to find significant dark spots (creases usually cast shadows).
    *   If large dark areas (>500px) are found, `major_damage_detected` is set to True.

4.  **Scoring (1-10 Scale):**
    *   **10.0:** 0 scratches.
    *   **9.5:** 1-3 scratches.
    *   **9.0:** 4-7 scratches.
    *   **8.0:** 8-12 scratches.
    *   **7.0:** 13-20 scratches.
    *   **6.5:** >20 scratches.
    *   **Cap:** If `major_damage_detected` is True, the score is capped at **7.0**.

---

## 3. Centering Analysis

**Location:** `backend/analysis/centering.py`

Determines how well-centered the artwork is on the card.

### Algorithm Steps:
1.  **Inner Box Detection:**
    *   Uses Gaussian Blur and Canny edge detection on the perspective-corrected image.
    *   Finds contours that represent the inner artwork frame.
    *   **Filtering:** Looks for a box that is 15-70% of the card area and located in the upper half (typical for Pokémon cards).

2.  **Measurement:**
    *   Calculates the width of borders in pixels: `Top`, `Bottom`, `Left`, `Right`.

3.  **Scoring Logic:**
    *   Calculates ratios: `Min(L, R) / Max(L, R)` and `Min(T, B) / Max(T, B)`.
    *   Averages these two ratios.
    *   **Linear Interpolation Scoring:**
        *   **10.0:** Ratio ≥ 0.975 (Virtual perfection)
        *   **9.0:** Ratio ≥ 0.95
        *   **8.0:** Ratio ≥ 0.90
        *   (and so on, smoothly interpolating down to 1.0)

---

## 4. Edge & Corner Detection

**Location:** `backend/analysis/edges.py`, `backend/analysis/corners.py`

Analyzes the physical condition of the card edges, looking for "whitening" (wear).

### Edge Analysis:
1.  **Masking:**
    *   Creates a `border_mask` focusing on the outer 3% of the card.
    *   **Blue Detection:** Verifies the region is blue (Pokemon card back) using HSV Color Space (Hue 90-140) to distinguish card border from background artifacting.

2.  **Whitening Detection:**
    *   Converts to LAB color space.
    *   Pixels with **Lightness (L) > 155** are flagged as "whitened" (wear exposing the white paper core).

3.  **Detailed Assessment:**
    *   Splits edges into Top, Bottom, Left, Right segments.
    *   Calculates `% whitening` for each segment.
    *   **Scoring:**
        *   **10.0 (Gem Mint):** < 0.2% whitening.
        *   **9.0 (Mint):** < 1.0% whitening.
        *   **8.0 (NM):** < 2.5% whitening.
        *   **Condition:** "Gem Mint", "Light Play", "Heavy Play" determined by score.

### Corner Analysis:
1.  **ROI Extraction:**
    *   Extracts a 60x60 pixel region at each of the 4 corners.
2.  **Wear Scoring:**
    *   Counts white pixels (HSV mask) in the corner region.
    *   **Smooth Scoring:** Interpolates based on pixel count:
        *   0-10 pixels: **10.0**
        *   30 pixels: **9.5**
        *   75 pixels: **9.0**
        *   ...
3.  **Final Grade:** Average of 4 corners, with a penalty applied if the "worst" corner is significantly damaged (e.g., a bent corner).
