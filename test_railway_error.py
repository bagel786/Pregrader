#!/usr/bin/env python3
"""
Quick test to see what error Railway is actually returning
"""
import requests
import json

BASE_URL = "https://pregrader-production.up.railway.app"

print("Testing Railway Backend Error...")
print("=" * 60)

# Test 1: Health check
print("\n1. Health Check:")
try:
    response = requests.get(f"{BASE_URL}/health", timeout=10)
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.json()}")
except Exception as e:
    print(f"   Error: {e}")

# Test 2: Try to trigger the error with a fake session
print("\n2. Testing /grade with fake session (should get 404):")
try:
    response = requests.post(
        f"{BASE_URL}/grade",
        params={"session_id": "fake-session-id"},
        timeout=10
    )
    print(f"   Status: {response.status_code}")
    print(f"   Response: {response.text}")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 60)
print("\nTo test with real upload, you need to:")
print("1. Upload an image first")
print("2. Get the session_id from the response")
print("3. Then call /grade with that session_id")
