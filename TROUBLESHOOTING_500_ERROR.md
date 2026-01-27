# Troubleshooting 500 Server Error on Railway

## What's Happening

You're getting a 500 Internal Server Error when trying to grade a card. This means the backend server is crashing or encountering an error during image analysis.

## Immediate Steps to Fix

### 1. Check Railway Logs (MOST IMPORTANT)

1. Go to [Railway Dashboard](https://railway.app)
2. Select your project
3. Click on "Deployments"
4. Click on the latest deployment
5. View the logs

**Look for:**
- Python error messages
- Stack traces
- "Analysis failed" messages
- Memory errors
- OpenCV errors

### 2. Verify Backend is Running

Test the health endpoint:
```bash
curl https://pregrader-production.up.railway.app/health
```

Expected response:
```json
{"status": "ok", "message": "Backend is running"}
```

If this fails, the server isn't running at all.

### 3. Test with a Simple Image

Try uploading a small, simple image first:
- Use a clear, well-lit photo
- Keep file size under 1MB
- Ensure it's JPEG or PNG format
- Make sure the card fills most of the frame

### 4. Check Environment Variables

In Railway dashboard, verify:
- `POKEMON_TCG_API_KEY` is set (get from https://pokemontcg.io)
- No other required variables are missing

## Common Causes & Solutions

### Cause 1: OpenCV Dependencies Missing

**Symptoms:**
- Server starts but crashes on first analysis
- Logs show "ImportError" or "cv2" errors

**Solution:**
The Dockerfile has been updated with all required dependencies. Redeploy:
```bash
cd backend
git add .
git commit -m "Update Dockerfile with OpenCV dependencies"
git push
```

Railway will automatically redeploy.

### Cause 2: Memory Limit Exceeded

**Symptoms:**
- Server crashes during analysis
- Logs show "Killed" or memory errors
- Works for small images but fails for large ones

**Solution:**
1. Upgrade Railway plan (Hobby → Pro)
2. Or reduce image size in Flutter app before upload

### Cause 3: Image Analysis Fails

**Symptoms:**
- Logs show "Card not detected" or "Analysis failed"
- Specific analysis module errors

**Solution:**
1. Ensure card is clearly visible in photo
2. Good lighting, no glare
3. Card should fill most of the frame
4. Try with the test images in `backend/analysis/test_images/`

### Cause 4: File Upload Issues

**Symptoms:**
- Upload succeeds but analysis fails
- Logs show file path errors

**Solution:**
The temp_uploads directory should be created automatically. If not:
```dockerfile
# Already added to Dockerfile
RUN mkdir -p temp_uploads && chmod 777 temp_uploads
```

## Testing Locally

Before deploying, test locally:

```bash
cd backend

# 1. Run startup check
python startup_check.py

# 2. Run analysis test
python test_analysis.py

# 3. Test with Docker
docker build -t pregrader-backend .
docker run -p 8000:8000 -e POKEMON_TCG_API_KEY=your_key pregrader-backend

# 4. Test endpoints
curl http://localhost:8000/health

# 5. Test upload (replace with actual image)
curl -X POST http://localhost:8000/analyze/upload \
  -F "front_image=@analysis/test_images/perfect.jpg"
```

## Detailed Debugging Steps

### Step 1: Enable Detailed Logging

The backend now has detailed logging. Check Railway logs for:

```
INFO - Upload started - Session ID: xxx
INFO - Analysis started - Session ID: xxx
ERROR - Analysis error - Session ID: xxx
```

### Step 2: Test Each Analysis Module

If logs show a specific module failing:

```bash
cd backend

# Test centering
python -c "from analysis.centering import calculate_centering_ratios; print(calculate_centering_ratios('analysis/test_images/perfect.jpg'))"

# Test corners
python -c "from analysis.corners import analyze_corner_wear; print(analyze_corner_wear('analysis/test_images/perfect.jpg'))"

# Test edges
python -c "from analysis.edges import analyze_edge_wear; print(analyze_edge_wear('analysis/test_images/perfect.jpg'))"

# Test surface
python -c "from analysis.surface import analyze_surface_damage; print(analyze_surface_damage('analysis/test_images/perfect.jpg'))"
```

### Step 3: Check Image Quality

The analysis might fail if:
- Image is too blurry
- Card edges not visible
- Too much glare
- Card not centered in frame
- Image resolution too low (< 500px) or too high (> 4000px)

### Step 4: Verify Railway Configuration

Check `backend/railway.toml`:
```toml
[build]
builder = "DOCKERFILE"

[deploy]
startCommand = "uvicorn main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
```

## Quick Fixes to Try

### Fix 1: Redeploy with Updated Code

```bash
cd backend
git pull  # Get latest fixes
git push  # Trigger redeploy
```

### Fix 2: Restart Railway Service

In Railway dashboard:
1. Go to your service
2. Click "Settings"
3. Click "Restart"

### Fix 3: Check Railway Status

Visit [Railway Status Page](https://status.railway.app) to see if there are any platform issues.

### Fix 4: Test with Postman/Insomnia

Use an API client to test the endpoints directly:

1. **Upload:**
   - POST `https://pregrader-production.up.railway.app/analyze/upload`
   - Body: form-data
   - Add file: `front_image` = your image file
   - Should return: `{"session_id": "xxx", ...}`

2. **Analyze:**
   - POST `https://pregrader-production.up.railway.app/grade?session_id=xxx`
   - Should return grading results

## Still Not Working?

### Collect This Information:

1. **Railway Logs** (last 100 lines)
2. **Error message** from Flutter app
3. **Image details:**
   - File size
   - Resolution
   - Format (JPEG/PNG)
4. **Test results:**
   - Does `/health` endpoint work?
   - Does upload succeed?
   - Does analysis fail?

### Contact Support:

With the above information, you can:
1. Check Railway community forums
2. Review FastAPI documentation
3. Test with the provided test scripts

## Prevention

To avoid future issues:

1. **Always test locally first** with `test_analysis.py`
2. **Monitor Railway logs** after deployment
3. **Use test images** before real cards
4. **Keep images under 2MB**
5. **Ensure good lighting** when capturing cards

## Updated Files

The following files have been updated to fix common issues:

- ✅ `backend/main.py` - Added detailed logging and error handling
- ✅ `backend/Dockerfile` - Added all OpenCV dependencies
- ✅ `backend/requirements.txt` - Added requests for health checks
- ✅ `backend/startup_check.py` - Verify dependencies on startup
- ✅ `backend/test_analysis.py` - Test analysis pipeline
- ✅ `lib/screens/review_screen.dart` - Better error messages

## Next Steps

1. Pull the latest code
2. Redeploy to Railway
3. Check logs for detailed error messages
4. Test with a simple, clear card photo
5. If still failing, share the Railway logs for further diagnosis
