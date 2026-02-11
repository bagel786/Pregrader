"""
Card Detection Debugger
Visualizes the detection process step-by-step to diagnose issues

Solves: "not sure what it's seeing"
"""
import cv2
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import uuid


class CardDetectionDebugger:
    """
    Debug tool to visualize card detection pipeline
    Saves images at each step to understand what's happening
    """
    
    def __init__(self, output_dir: str = "./debug_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def visualize_full_pipeline(
        self,
        image_path: str,
        session_id: Optional[str] = None
    ) -> Dict:
        """
        Run full detection pipeline with visualization
        
        Saves images showing:
        1. Original image
        2. Grayscale conversion
        3. Blur application
        4. Edge detection (multiple methods)
        5. Contour detection
        6. Candidate filtering
        7. Final result
        
        Returns dict with paths to debug images and detection results
        """
        if session_id is None:
            session_id = str(uuid.uuid4())[:8]
        
        session_dir = self.output_dir / session_id
        session_dir.mkdir(exist_ok=True)
        
        results = {
            "session_id": session_id,
            "debug_dir": str(session_dir),
            "steps": {}
        }
        
        # Load image
        img = cv2.imread(image_path)
        if img is None:
            results["error"] = f"Could not load image: {image_path}"
            return results
        
        h, w = img.shape[:2]
        results["original_size"] = (w, h)
        
        # Step 1: Original
        cv2.imwrite(str(session_dir / "01_original.jpg"), img)
        results["steps"]["original"] = "01_original.jpg"
        
        # Step 2: Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cv2.imwrite(str(session_dir / "02_grayscale.jpg"), gray)
        results["steps"]["grayscale"] = "02_grayscale.jpg"
        
        # Step 3: Blur
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        cv2.imwrite(str(session_dir / "03_blurred.jpg"), blurred)
        results["steps"]["blurred"] = "03_blurred.jpg"
        
        # Step 4: Edge detection (multiple methods)
        edges_methods = {
            "canny_normal": cv2.Canny(blurred, 50, 150),
            "canny_sensitive": cv2.Canny(blurred, 30, 100),
            "canny_aggressive": cv2.Canny(blurred, 100, 200),
        }
        
        for method_name, edges in edges_methods.items():
            filename = f"04{chr(97 + list(edges_methods.keys()).index(method_name))}_edges_{method_name}.jpg"
            cv2.imwrite(str(session_dir / filename), edges)
            results["steps"][f"edges_{method_name}"] = filename
        
        # Step 5: Morphological operations
        kernel = np.ones((3, 3), np.uint8)
        morph = cv2.morphologyEx(edges_methods["canny_normal"], cv2.MORPH_CLOSE, kernel, iterations=2)
        cv2.imwrite(str(session_dir / "05_morphological.jpg"), morph)
        results["steps"]["morphological"] = "05_morphological.jpg"
        
        # Step 6: Find contours and visualize candidates
        contours, _ = cv2.findContours(edges_methods["canny_normal"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Draw all contours
        all_contours_img = img.copy()
        cv2.drawContours(all_contours_img, contours, -1, (0, 255, 0), 2)
        cv2.imwrite(str(session_dir / "06_all_contours.jpg"), all_contours_img)
        results["steps"]["all_contours"] = "06_all_contours.jpg"
        results["total_contours"] = len(contours)
        
        # Filter candidates
        min_area = 0.20 * (w * h)
        max_area = 0.90 * (w * h)
        target_aspect = 0.714  # Pokemon card aspect ratio
        
        candidates = []
        candidates_img = img.copy()
        
        for i, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            
            # Check area
            if area < min_area or area > max_area:
                continue
            
            # Check aspect ratio
            rect = cv2.minAreaRect(cnt)
            box_w, box_h = rect[1]
            if box_h == 0:
                continue
            
            aspect = box_w / box_h
            aspect_diff = min(abs(aspect - target_aspect), abs(aspect - (1/target_aspect)))
            
            if aspect_diff > 0.15:
                continue
            
            # This is a candidate
            score = (area / (w * h)) * (1 - aspect_diff)
            candidates.append({
                "index": i,
                "area": area,
                "aspect": aspect,
                "score": score,
                "contour": cnt
            })
            
            # Draw candidate
            color = (0, 255, 0) if score > 0.5 else (0, 165, 255)
            cv2.drawContours(candidates_img, [cnt], -1, color, 3)
            
            # Add label
            M = cv2.moments(cnt)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                cv2.putText(candidates_img, f"#{i}: {score:.2f}", 
                           (cx - 50, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        
        cv2.imwrite(str(session_dir / "07_candidates.jpg"), candidates_img)
        results["steps"]["candidates"] = "07_candidates.jpg"
        results["candidates"] = len(candidates)
        
        # Step 7: Best candidate
        if candidates:
            best = max(candidates, key=lambda x: x["score"])
            best_img = img.copy()
            cv2.drawContours(best_img, [best["contour"]], -1, (0, 255, 0), 3)
            
            # Get corners
            peri = cv2.arcLength(best["contour"], True)
            approx = cv2.approxPolyDP(best["contour"], 0.02 * peri, True)
            
            if len(approx) >= 4:
                # Draw corners
                for point in approx[:4]:
                    cv2.circle(best_img, tuple(point[0]), 10, (0, 0, 255), -1)
                
                cv2.imwrite(str(session_dir / "08_best_candidate.jpg"), best_img)
                results["steps"]["best_candidate"] = "08_best_candidate.jpg"
                results["best_score"] = best["score"]
                results["corners_found"] = len(approx)
                
                # Step 8: Apply perspective correction
                if len(approx) == 4:
                    corners = self._order_points(approx.reshape(-1, 2))
                    dst_pts = np.array([[0, 0], [499, 0], [499, 699], [0, 699]], dtype=np.float32)
                    M = cv2.getPerspectiveTransform(corners, dst_pts)
                    warped = cv2.warpPerspective(img, M, (500, 700))
                    
                    cv2.imwrite(str(session_dir / "09_corrected.jpg"), warped)
                    results["steps"]["corrected"] = "09_corrected.jpg"
                    results["corrected"] = True
                else:
                    results["corrected"] = False
                    results["correction_error"] = f"Need 4 corners, got {len(approx)}"
            else:
                results["corrected"] = False
                results["correction_error"] = f"Approximation gave {len(approx)} points"
        else:
            results["corrected"] = False
            results["correction_error"] = "No candidates found"
        
        return results
    
    def diagnose_detection_failure(self, image_path: str) -> str:
        """
        Analyze why detection might be failing
        
        Returns human-readable diagnosis
        """
        img = cv2.imread(image_path)
        if img is None:
            return "❌ Could not load image"
        
        h, w = img.shape[:2]
        diagnosis = []
        
        # Check 1: Image size
        if w < 300 or h < 300:
            diagnosis.append("⚠️  Image is very small (< 300px). Try higher resolution.")
        elif w > 4000 or h > 4000:
            diagnosis.append("⚠️  Image is very large (> 4000px). Consider resizing.")
        else:
            diagnosis.append("✅ Image size is reasonable")
        
        # Check 2: Brightness
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        avg_brightness = np.mean(gray)
        
        if avg_brightness < 50:
            diagnosis.append("⚠️  Image is very dark. Improve lighting.")
        elif avg_brightness > 200:
            diagnosis.append("⚠️  Image is very bright/washed out. Reduce exposure.")
        else:
            diagnosis.append("✅ Brightness is good")
        
        # Check 3: Contrast
        contrast = np.std(gray)
        
        if contrast < 30:
            diagnosis.append("⚠️  Low contrast. Card may blend with background.")
        else:
            diagnosis.append("✅ Contrast is sufficient")
        
        # Check 4: Blur
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        if laplacian_var < 100:
            diagnosis.append("⚠️  Image appears blurry. Hold camera steady.")
        else:
            diagnosis.append("✅ Image is sharp")
        
        # Check 5: Edge detection
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        
        if edge_density < 0.01:
            diagnosis.append("⚠️  Very few edges detected. Check lighting and contrast.")
        elif edge_density > 0.3:
            diagnosis.append("⚠️  Too many edges (busy background?). Use plain background.")
        else:
            diagnosis.append("✅ Edge density is good")
        
        # Check 6: Contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        large_contours = [c for c in contours if cv2.contourArea(c) > 0.1 * (w * h)]
        
        if len(large_contours) == 0:
            diagnosis.append("⚠️  No large contours found. Card may not be visible.")
        elif len(large_contours) > 5:
            diagnosis.append("⚠️  Many large contours (cluttered background?). Simplify scene.")
        else:
            diagnosis.append("✅ Contour count is reasonable")
        
        return "\n".join(diagnosis)
    
    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """Order points: TL, TR, BR, BL"""
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        diff = np.diff(pts, axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect
    
    def compare_methods(self, image_path: str) -> Dict:
        """
        Compare different detection methods side-by-side
        """
        img = cv2.imread(image_path)
        if img is None:
            return {"error": "Could not load image"}
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        methods = {
            "Standard Canny": cv2.Canny(blurred, 50, 150),
            "Sensitive Canny": cv2.Canny(blurred, 30, 100),
            "Aggressive Canny": cv2.Canny(blurred, 100, 200),
            "Adaptive Threshold": cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            ),
        }
        
        results = {}
        
        for method_name, edges in methods.items():
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Count valid candidates
            h, w = img.shape[:2]
            min_area = 0.20 * (w * h)
            max_area = 0.90 * (w * h)
            
            candidates = sum(1 for c in contours if min_area <= cv2.contourArea(c) <= max_area)
            
            results[method_name] = {
                "total_contours": len(contours),
                "candidates": candidates,
                "edge_density": np.sum(edges > 0) / edges.size
            }
        
        return results


# CLI interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python debugger.py <image_path> [output_dir]")
        sys.exit(1)
    
    image_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./debug_output"
    
    debugger = CardDetectionDebugger(output_dir=output_dir)
    
    print("Running full pipeline visualization...")
    results = debugger.visualize_full_pipeline(image_path)
    
    print(f"\nDebug images saved to: {results['debug_dir']}")
    print(f"Total contours: {results.get('total_contours', 0)}")
    print(f"Candidates: {results.get('candidates', 0)}")
    print(f"Corrected: {results.get('corrected', False)}")
    
    if not results.get('corrected'):
        print(f"Error: {results.get('correction_error', 'Unknown')}")
    
    print("\nRunning diagnosis...")
    diagnosis = debugger.diagnose_detection_failure(image_path)
    print(diagnosis)
    
    print("\nComparing methods...")
    comparison = debugger.compare_methods(image_path)
    for method, stats in comparison.items():
        print(f"\n{method}:")
        print(f"  Contours: {stats['total_contours']}")
        print(f"  Candidates: {stats['candidates']}")
        print(f"  Edge density: {stats['edge_density']:.3f}")
