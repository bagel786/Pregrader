# Quick Reference - Hybrid Detection System

## 🚀 Deploy to Railway (5 minutes)

```bash
# 1. Commit and push
git add .
git commit -m "Add hybrid card detection system"
git push origin main

# 2. Set environment variable in Railway Dashboard
# Go to: Railway Dashboard → Your Project → Variables → Add
ANTHROPIC_API_KEY=your-anthropic-api-key-here

# 3. Railway auto-deploys - wait for build to complete
```

## 📱 Update Flutter App

Change API endpoint from v1 to v2:

```dart
// OLD
final url = '$baseUrl/api/grading/$sessionId/upload-front';

// NEW (for testing hybrid detection)
final url = '$baseUrl/api/v2/grading/$sessionId/upload-front';
```

## 🧪 Test on iPhone

```bash
# Build and deploy
flutter build ios
# Open in Xcode and deploy to device
```

Test these scenarios:
1. ✅ Plain background → Should be fast (~30ms)
2. ✅ Busy background → May take 2-3s (AI fallback)
3. ✅ Angled card → Should work (AI handles it)
4. ✅ Corner damage → Should detect accurately
5. ✅ Glare → Should filter false positives

## 📊 Monitor Performance

```bash
# Check detection stats
curl https://your-app.railway.app/api/v2/admin/detection-stats

# Expected output:
{
  "total_detections": 50,
  "success_rate": 0.94,
  "method_usage": {
    "opencv": 0.68,      # 68% used fast path
    "hybrid_ai": 0.32    # 32% needed AI
  },
  "avg_processing_time_ms": 450
}
```

## 🔍 Debug Issues

View what was detected:
```
https://your-app.railway.app/api/v2/debug/{session_id}/visualization
```

## 🎛️ Tune Performance

### Use AI Less (Lower Cost)
```bash
# In Railway: Variables → Edit
OPENCV_CONFIDENCE_THRESHOLD=0.65
# Result: 20-25% AI usage, ~$0.004/grading
```

### Use AI More (Higher Accuracy)
```bash
OPENCV_CONFIDENCE_THRESHOLD=0.80
# Result: 45-55% AI usage, ~$0.010/grading
```

### Disable AI (Free but Lower Accuracy)
```bash
DEFAULT_DETECTION_METHOD=opencv
# Result: 0% AI usage, $0/grading, ~75% success rate
```

## 🔒 Security

- ✅ API key in `.env` (gitignored)
- ✅ Set in Railway as environment variable
- ✅ Never committed to GitHub
- ✅ Never exposed in API responses

## 💰 Cost Tracking

Monitor in Anthropic Dashboard:
https://console.anthropic.com/

Expected costs:
- Per grading: ~$0.006
- 100/day: ~$18/month
- 500/day: ~$90/month
- 1000/day: ~$180/month

## 📚 Documentation

- `IMPLEMENTATION_SUMMARY.md` - Overview
- `backend/HYBRID_DETECTION_ARCHITECTURE.md` - How it works
- `DEPLOYMENT_CHECKLIST.md` - Step-by-step guide
- `SETUP_COMPLETE.md` - Quick start

## 🆘 Troubleshooting

### Detection Fails
1. Check debug visualization
2. Review Railway logs: `railway logs | grep error`
3. Check detection stats

### High Costs
1. Check AI usage percentage
2. Lower threshold: `OPENCV_CONFIDENCE_THRESHOLD=0.65`
3. Monitor daily costs

### Slow Performance
1. Check if AI is being used too often
2. Increase threshold: `OPENCV_CONFIDENCE_THRESHOLD=0.75`
3. Check `avg_processing_time_ms` in stats

## ✅ Success Metrics

After 1 week, you should see:
- ✅ Success rate: >90%
- ✅ OpenCV usage: 60-70%
- ✅ AI usage: 30-40%
- ✅ Average time: <1s
- ✅ Cost: <$10/day for 1000 gradings

---

**Status:** Ready for deployment
**Next:** Deploy to Railway and test on iPhone
