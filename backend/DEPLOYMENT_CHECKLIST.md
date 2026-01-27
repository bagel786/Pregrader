# Deployment Checklist for Railway

## Pre-Deployment Testing

- [ ] Run `python startup_check.py` - All checks pass
- [ ] Run `python test_analysis.py` - Analysis pipeline works
- [ ] Test locally with Docker:
  ```bash
  docker build -t pregrader-backend .
  docker run -p 8000:8000 -e POKEMON_TCG_API_KEY=your_key pregrader-backend
  ```
- [ ] Test health endpoint: `curl http://localhost:8000/health`
- [ ] Test upload endpoint with sample images
- [ ] Test analysis endpoint with uploaded session

## Railway Configuration

- [ ] Repository connected to Railway
- [ ] Root directory set to `backend`
- [ ] Environment variables configured:
  - [ ] `POKEMON_TCG_API_KEY` set
  - [ ] `PORT` set to 8000 (optional, Railway sets this automatically)
- [ ] Dockerfile detected and used for build
- [ ] Health check configured: `/health`

## Post-Deployment Verification

- [ ] Deployment successful (check Railway dashboard)
- [ ] Health endpoint responds: `https://your-app.up.railway.app/health`
- [ ] No errors in Railway logs
- [ ] Test upload from Flutter app
- [ ] Test full grading flow
- [ ] Check response times (should be < 10s for analysis)

## Common Issues & Solutions

### Issue: Build fails
**Check:**
- Dockerfile syntax
- All files present in backend directory
- Railway build logs for specific error

### Issue: Server starts but crashes on first request
**Check:**
- Railway logs for Python errors
- OpenCV dependencies (should be in Dockerfile)
- Memory usage (upgrade plan if needed)

### Issue: 500 errors on /analyze endpoint
**Check:**
- Image file format (JPEG/PNG)
- Image file size (< 5MB recommended)
- Railway logs for detailed error message
- Test with test_analysis.py locally first

### Issue: Slow response times
**Solutions:**
- Upgrade Railway plan for more CPU/RAM
- Optimize image size in Flutter app before upload
- Consider adding Redis for session caching

## Monitoring Setup

- [ ] Enable Railway metrics
- [ ] Set up deployment notifications
- [ ] Configure alerts for:
  - [ ] High memory usage (> 80%)
  - [ ] High error rate (> 5%)
  - [ ] Deployment failures

## Rollback Plan

If deployment fails:
1. Check Railway logs for errors
2. Revert to previous deployment in Railway dashboard
3. Fix issues locally and test
4. Redeploy

## Performance Benchmarks

Expected performance on Railway Hobby plan:
- Health check: < 100ms
- Image upload: < 2s (depends on image size)
- Analysis: 5-10s per card
- Memory usage: 200-400MB

## Security Checklist

- [ ] CORS configured correctly (restrict origins in production)
- [ ] API keys stored in environment variables (not in code)
- [ ] File upload size limits enforced
- [ ] Temp files cleaned up after analysis
- [ ] HTTPS enabled (automatic on Railway)

## Next Steps After Deployment

1. Update Flutter app with Railway URL
2. Test end-to-end flow
3. Monitor logs for first few hours
4. Collect user feedback
5. Optimize based on usage patterns
