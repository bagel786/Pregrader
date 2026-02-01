#!/usr/bin/env python3
"""
Consistency testing for grading system.
Tests that the same image produces consistent grades across multiple runs.
"""
import sys
import json
from pathlib import Path
import numpy as np

def test_grading_consistency(image_path, num_trials=10):
    """
    Test how consistent grading is for the same image.
    
    Args:
        image_path: Path to test image
        num_trials: Number of times to grade the same image
    
    Returns:
        Success/failure boolean
    """
    print(f"Testing grading consistency on: {image_path}")
    print(f"Running {num_trials} trials...")
    print("=" * 60)
    
    # Import analysis modules
    try:
        from analysis.centering import calculate_centering_ratios
        from analysis.corners import analyze_corner_wear
        from analysis.edges import analyze_edge_wear
        from analysis.surface import analyze_surface_damage
        from analysis.scoring import GradingEngine
    except Exception as e:
        print(f"✗ Failed to import analysis modules: {e}")
        return False
    
    grades = []
    confidences = []
    
    for i in range(num_trials):
        try:
            # Run full analysis
            centering_result = calculate_centering_ratios(image_path)
            corners_result = analyze_corner_wear(image_path)
            edges_result = analyze_edge_wear(image_path)
            surface_result = analyze_surface_damage(image_path)
            
            # Calculate grade
            grading_result = GradingEngine.calculate_grade(
                centering_score=centering_result.get("grade_estimate", 8.0),
                corners_data=corners_result,
                edges_data=edges_result,
                surface_data=surface_result["surface"]
            )
            
            grades.append(grading_result['final_score'])
            confidences.append(grading_result['confidence'][ 'overall'])
            
        except Exception as e:
            print(f"✗ Trial {i+1} failed: {e}")
            return False
    
    # Calculate statistics
    mean_grade = np.mean(grades)
    std_dev = np.std(grades)
    min_grade = min(grades)
    max_grade = max(grades)
    variance = max_grade - min_grade
    mean_confidence = np.mean(confidences)
    
    print(f"\n📊 Results:")
    print(f"   Mean Grade:    {mean_grade:.2f}")
    print(f"   Std Deviation: {std_dev:.3f}")
    print(f"   Range:         {min_grade:.1f} - {max_grade:.1f}")
    print(f"   Variance:      {variance:.2f} points")
    print(f"   Avg Confidence: {mean_confidence:.2f}")
    
    print(f"\n  All grades: {[f'{g:.1f}' for g in grades]}")
    
    # Goal: variance < 0.5 points
    print("\n" + "=" * 60)
    if variance < 0.5:
        print("✅ PASS: Grading is CONSISTENT (variance < 0.5 points)")
        return True
    elif variance < 1.0:
        print("⚠️  WARNING: Grading shows some variance (0.5-1.0 points)")
        print("   This is acceptable but could be improved")
        return True
    else:
        print("❌ FAIL: Grading is INCONSISTENT (variance >= 1.0 points)")
        print("   The same card should not vary by more than 1 point")
        return False


def main():
    """Run consistency tests on all test images."""
    test_images_dir = Path(__file__).parent / "analysis" / "test_images"
    
    if not test_images_dir.exists():
        print(f"✗ Test images directory not found: {test_images_dir}")
        return False
    
    test_images = list(test_images_dir.glob("*.jpg")) + list(test_images_dir.glob("*.png"))
    
    if not test_images:
        print(f"✗ No test images found in {test_images_dir}")
        return False
    
    print(f"\n🧪 Consistency Testing Suite")
    print(f"Found {len(test_images)} test images\n")
    
    all_passed = True
    
    for image_path in test_images[:3]:  # Test first 3 images
        success = test_grading_consistency(str(image_path), num_trials=5)
        all_passed = all_passed and success
        print()
    
    if all_passed:
        print("\n" + "=" * 60)
        print("✅ ALL CONSISTENCY TESTS PASSED")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ SOME TESTS FAILED")
        print("=" * 60)
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
