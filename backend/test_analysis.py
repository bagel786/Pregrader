#!/usr/bin/env python3
"""
Test script to verify the analysis pipeline works correctly.
Use this to test locally before deploying to Railway.
"""
import sys
import json
from pathlib import Path

# Test with a sample image
def test_analysis_pipeline():
    """Test the full analysis pipeline."""
    print("Testing Analysis Pipeline...")
    print("=" * 50)
    
    # Import analysis modules
    try:
        from analysis.centering import calculate_centering_ratios
        from analysis.corners import analyze_corner_wear
        from analysis.edges import analyze_edge_wear
        from analysis.surface import analyze_surface_damage
        from analysis.scoring import GradingEngine
        print("✓ All analysis modules imported successfully")
    except Exception as e:
        print(f"✗ Failed to import analysis modules: {e}")
        return False
    
    # Check for test images
    test_images_dir = Path(__file__).parent / "analysis" / "test_images"
    if not test_images_dir.exists():
        print(f"✗ Test images directory not found: {test_images_dir}")
        return False
    
    test_images = list(test_images_dir.glob("*.jpg")) + list(test_images_dir.glob("*.png"))
    if not test_images:
        print(f"✗ No test images found in {test_images_dir}")
        return False
    
    print(f"✓ Found {len(test_images)} test images")
    
    # Test with first image
    test_image = str(test_images[0])
    print(f"\nTesting with: {test_image}")
    print("-" * 50)
    
    try:
        # Run centering analysis
        print("\n1. Testing Centering Analysis...")
        centering_result = calculate_centering_ratios(test_image)
        if "error" in centering_result:
            print(f"   Warning: {centering_result['error']}")
        else:
            print(f"   ✓ Centering grade: {centering_result.get('grade_estimate', 'N/A')}")
        
        # Run corners analysis
        print("\n2. Testing Corners Analysis...")
        corners_result = analyze_corner_wear(test_image)
        if "error" in corners_result:
            print(f"   ✗ Error: {corners_result['error']}")
            return False
        else:
            avg_score = sum(c["score"] for c in corners_result["corners"].values()) / 4
            print(f"   ✓ Average corner score: {avg_score:.1f}")
        
        # Run edges analysis
        print("\n3. Testing Edges Analysis...")
        edges_result = analyze_edge_wear(test_image)
        if "error" in edges_result:
            print(f"   ✗ Error: {edges_result['error']}")
            return False
        else:
            avg_score = sum(e["score"] for e in edges_result["edges"].values()) / 4
            print(f"   ✓ Average edge score: {avg_score:.1f}")
        
        # Run surface analysis
        print("\n4. Testing Surface Analysis...")
        surface_result = analyze_surface_damage(test_image)
        if "error" in surface_result:
            print(f"   ✗ Error: {surface_result['error']}")
            return False
        else:
            print(f"   ✓ Surface score: {surface_result['surface']['score']:.1f}")
        
        # Run grading
        print("\n5. Testing Grading Engine...")
        grading_result = GradingEngine.calculate_grade(
            centering_score=centering_result.get("grade_estimate", 8.0),
            corners_data=corners_result,
            edges_data=edges_result,
            surface_data=surface_result["surface"]
        )
        
        print(f"   ✓ Final Grade: {grading_result['psa_estimate']}")
        print(f"   ✓ Final Score: {grading_result['final_score']}")
        print(f"   ✓ Confidence: {grading_result['confidence']}")
        
        print("\n" + "=" * 50)
        print("✓ All tests passed!")
        print("=" * 50)
        
        # Print full result
        print("\nFull Grading Result:")
        print(json.dumps(grading_result, indent=2))
        
        return True
        
    except Exception as e:
        import traceback
        print(f"\n✗ Test failed with error:")
        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    success = test_analysis_pipeline()
    sys.exit(0 if success else 1)
