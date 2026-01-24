import cv2
import numpy as np

def calculate_centering_ratios(image_path: str) -> dict:
    """
    Analyzes a Pokemon card image to determine centering ratios.
    Assumes the image contains a single card, ideally cropped or on a plain background.
    """
    try:
        # 1. Load Image
        image = cv2.imread(image_path)
        if image is None:
            return {"error": "Failed to load image"}

        # 2. Preprocessing
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        # 3. Find Contours
        contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        # 5. Identify Borders using Hierarchical Search
        # Strategy:
        # A. Find the largest card-like contour (Outer Border)
        # B. Create a Region of Interest (ROI) from this contour
        # C. Search for the largest contour *inside* the ROI (Inner Border)
        
        candidates = []
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            if len(approx) == 4:
                rect = cv2.boundingRect(approx)
                area = rect[2] * rect[3]
                if area > 1000:
                    candidates.append((area, rect, approx))
        
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        if not candidates:
             return {"error": "No card detected."}

        # Assume largest is the card
        outer_area, outer_rect, outer_approx = candidates[0]
        ox, oy, ow, oh = outer_rect
        
        # Extract ROI (with small padding to avoid edge noise)
        roi = image[oy:oy+oh, ox:ox+ow]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_blur = cv2.GaussianBlur(roi_gray, (5, 5), 0)
        # Use different Canny thresholds for inner detail
        roi_edges = cv2.Canny(roi_blur, 30, 100)
        
        roi_contours, _ = cv2.findContours(roi_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        inner_candidates = []
        for cnt in roi_contours:
            perimeter = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * perimeter, True)
            
            if len(approx) == 4:
                rect = cv2.boundingRect(approx)
                ix, iy, iw, ih = rect
                area = iw * ih
                
                # Check if it's substantially smaller than the outer box (to avoid re-detecting the outer edge)
                # but large enough to be the artwork
                # Artwork is usually ~60-80% of the card area
                if area < (outer_area * 0.95) and area > (outer_area * 0.3):
                    inner_candidates.append((area, rect))

        inner_candidates.sort(key=lambda x: x[0], reverse=True)
        
        if not inner_candidates:
             return {
                "error": "Card found, but inner artwork frame not detected.",
                "debug_info": f"Outer: {outer_rect}."
            }
            
        # Best inner rect relative to ROI
        _, (rix, riy, riw, rih) = inner_candidates[0]
        
        # Map back to global coordinates
        ix = ox + rix
        iy = oy + riy
        iw = riw
        ih = rih
        
        inner_rect = (ix, iy, iw, ih)

        # 6. Calculate Border Widths
        left_border = rix # x-offset in ROI is exactly the left border
        top_border = riy  # y-offset in ROI is exactly the top border
        right_border = ow - (rix + riw)
        bottom_border = oh - (riy + rih)

        # 7. Calculate Ratios
        total_width = left_border + right_border
        total_height = top_border + bottom_border

        if total_width == 0: total_width = 1 # Safety
        if total_height == 0: total_height = 1 # Safety

        lr_split = (left_border / total_width) * 100
        rl_split = (right_border / total_width) * 100
        
        tb_split = (top_border / total_height) * 100
        bt_split = (bottom_border / total_height) * 100
        
        # Grade Estimation
        score_h = max(lr_split, rl_split)
        score_v = max(tb_split, bt_split)
        
        est_grade = 10
        if score_h > 60 or score_v > 60: est_grade = 9
        if score_h > 65 or score_v > 65: est_grade = 8
        if score_h > 70 or score_v > 70: est_grade = 7
        if score_h > 80 or score_v > 80: est_grade = 6 # Very off-center

        return {
            "horizontal": {
                "left_px": left_border,
                "right_px": right_border,
                "ratio_left": round(lr_split, 1),
                "ratio_right": round(rl_split, 1),
                "label": f"{round(max(lr_split, rl_split),0)}/{round(min(lr_split, rl_split),0)}"
            },
            "vertical": {
                "top_px": top_border,
                "bottom_px": bottom_border,
                "ratio_top": round(tb_split, 1),
                "ratio_bottom": round(bt_split, 1),
                 "label": f"{round(max(tb_split, bt_split),0)}/{round(min(tb_split, bt_split),0)}"
            },
            "grade_estimate": est_grade
        }


    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # Test Block
    import sys
    if len(sys.argv) > 1:
        print(calculate_centering_ratios(sys.argv[1]))
    else:
        print("Usage: python centering.py <image_path>")
