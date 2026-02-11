# Hybrid Detection Deployment Checklist

## ✅ Setup Complete

- [x] Created `backend/services/ai/vision_detector.py`
- [x] Created `backend/analysis/vision/debugger.py`
- [x] Copied `backend/analysis/enhanced_corners.py`
- [x] Copied `backend/api/enhanced_detection.py`
- [x] Copied `backend/test_before_deploy.py`
- [x] Updated `backend/main.py` with enhanced router
- [x] Verified `requirements.txt` has httpx
- [x] All files pass Python syntax check
- [x] All modules import successfully

## 📋 Before You Deploy

### 1. Get API Key
- [ ] Go to https://console.anthropic.com/
- [ ] Sign up / Log in
- [ ] Create API key (starts with `sk-ant-`)
- [ ] Copy and save the key securely

### 2. Test Locally
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
cd backend
python3 test_before_deploy.py path/to/test_card.jpg
```

- [ ] All 8 tests pass
- [ ] Card detected successfully
- [ ] Debug images generated
- [ ] Corner analysis works
- [ ] No import errors

### 3. Set Railway Environment Variables

In Railway Dashboard → Variables:

- [ ] `ANTHROPIC_API_KEY` = `sk-ant-your-key`
- [ ] `DEFAULT_DETECTION_METHOD` = `hybrid` (optional)
- [ ] `OPENCV_CONFIDENCE_THRESHOLD` = `0.70` (optional)
- [ ] `ENABLE_DEBUG_IMAGES` = `true` (optional)

### 4. Deploy to Railway

```bash
git add .
git commit -m "Add hybrid card detection with visual debugging"
git push origin main
```

- [ ] Railway build succeeds
- [ ] No errors in Railway logs
- [ ] Health check returns 200

### 5. Test on Railway

```bash
RAILWAY_URL="https://your-app.up.railway.app"

# Test health
curl "$RAILWAY_URL/health"

# Start session
SESSION=$(curl -s -X POST "$RAILWAY_URL/api/v2/grading/start" | jq -r '.session_id')

# Upload card
curl -X POST "$RAILWAY_URL/api/v2/grading/$SESSION/upload-front" \
  -F "file=@test_card.jpg" | jq

# View debug
open "$RAILWAY_URL/api/v2/debug/$SESSION/visualization"
```

- [ ] Session created successfully
- [ ] Card upload returns success
- [ ] Debug visualization shows correct detection
- [ ] Corner scores are reasonable
- [ ] Processing time < 5 seconds

## 📊 Week 1 Monitoring

### Daily Checks

- [ ] Check detection stats: `curl $RAILWAY_URL/api/v2/admin/detection-stats`
- [ ] Review Railway logs for errors
- [ ] Monitor API costs in Anthropic dashboard
- [ ] Test with problem images from users

### Success Metrics to Track

- [ ] Detection success rate > 90%
- [ ] OpenCV usage 60-70% (fast path)
- [ ] AI usage 30-40% (difficult images)
- [ ] Corner false positives reduced
- [ ] User retake rate decreased
- [ ] Average cost per grading < $0.01

## 🔧 Tuning (If Needed)

### If Too Many AI Calls (High Cost)

```bash
# Use OpenCV more aggressively
railway variables set OPENCV_CONFIDENCE_THRESHOLD=0.65
```

### If Too Many Failures (Low Accuracy)

```bash
# Use AI more often
railway variables set OPENCV_CONFIDENCE_THRESHOLD=0.80
```

### If Corner False Positives Still High

Edit `backend/analysis/enhanced_corners.py`:
- Adjust `_is_false_positive()` thresholds
- Modify `_check_edge_whitening()` parameters
- Tune `_is_in_corner_zone()` zone size

## 🚨 Rollback Plan

If something goes wrong:

### Option 1: Disable AI (Keep Code)
```bash
railway variables set DEFAULT_DETECTION_METHOD=opencv
```

### Option 2: Full Rollback
```bash
git revert HEAD
git push origin main
```

### Option 3: Disable New Endpoint
Comment out in `backend/main.py`:
```python
# app.include_router(enhanced_router, prefix="/api/v2")
```

## 📚 Documentation

- Setup guide: `backend/HYBRID_DETECTION_SETUP.md`
- Migration guide: `Updates+plans/MIGRATION_GUIDE.md`
- Railway guide: `Updates+plans/RAILWAY_DEPLOYMENT.md`
- Backend details: `Updates+plans/README_FOR_YOUR_BACKEND.md`

## ✅ Final Verification

Before marking as complete:

- [ ] Local tests pass
- [ ] Railway deployment successful
- [ ] New endpoints respond correctly
- [ ] Debug visualizations work
- [ ] No errors in logs
- [ ] API key is set and working
- [ ] Cost monitoring in place
- [ ] Team knows about new endpoints

---

**Current Status:** Setup Complete ✅

**Next Step:** Run local tests with `python3 backend/test_before_deploy.py`
