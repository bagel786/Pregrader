#!/bin/bash

# Test Railway endpoint to diagnose 500 error

BASE_URL="https://pregrader-production.up.railway.app"

echo "================================"
echo "Testing Railway Backend"
echo "================================"
echo ""

# Test 1: Health check
echo "1. Testing health endpoint..."
curl -s "$BASE_URL/health" | python3 -m json.tool
echo ""
echo ""

# Test 2: Upload a test image
echo "2. Testing upload endpoint..."
echo "   (This will fail if no test image is provided)"
echo ""

# You would need to provide an actual image file here
# Example:
# SESSION_ID=$(curl -s -X POST "$BASE_URL/analyze/upload" \
#   -F "front_image=@backend/analysis/test_images/perfect.jpg" \
#   | python3 -c "import sys, json; print(json.load(sys.stdin)['session_id'])")
# 
# echo "   Session ID: $SESSION_ID"
# echo ""
# 
# # Test 3: Run analysis
# echo "3. Testing analysis endpoint..."
# curl -s -X POST "$BASE_URL/grade?session_id=$SESSION_ID" | python3 -m json.tool

echo "To test upload and analysis, run:"
echo "  curl -X POST $BASE_URL/analyze/upload -F 'front_image=@path/to/image.jpg'"
echo ""
