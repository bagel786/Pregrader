# Railway Deployment Guide

## Quick Deploy

1. **Connect Repository to Railway**
   - Go to [Railway.app](https://railway.app)
   - Create new project from GitHub repo
   - Select the `backend` directory as root

2. **Environment Variables**
   Add these in Railway dashboard:
   ```
   POKEMON_TCG_API_KEY=your_api_key_here
   PORT=8000
   ```

3. **Deploy Settings**
   - Railway will automatically detect the Dockerfile
   - Health check endpoint: `/health`
   - The service will be available at: `https://your-app.up.railway.app`

## Troubleshooting 500 Errors

### Check Railway Logs
1. Go to your Railway project
2. Click on "Deployments"
3. View the logs for error messages

### Common Issues

#### 1. OpenCV Dependencies Missing
**Symptom**: Server crashes on image analysis
**Solution**: The Dockerfile includes all required system libraries. If still failing, check logs for specific missing libraries.

#### 2. Memory Issues
**Symptom**: Server crashes during analysis or 500 errors
**Solution**: 
- Upgrade Railway plan for more memory
- Or reduce image size before upload in the Flutter app

#### 3. File Upload Issues
**Symptom**: Upload succeeds but analysis fails
**Solution**: 
- Check that temp_uploads directory is writable
- Verify file paths in logs
- Ensure images are valid JPEG/PNG

#### 4. API Key Issues
**Symptom**: Pokemon TCG API calls fail
**Solution**: 
- Verify POKEMON_TCG_API_KEY is set in Railway environment variables
- Get a free API key from https://pokemontcg.io

### Debug Endpoints

Test these endpoints to isolate issues:

```bash
# Health check
curl https://your-app.up.railway.app/health

# Test upload (replace with actual image)
curl -X POST https://your-app.up.railway.app/analyze/upload \
  -F "front_image=@card_front.jpg" \
  -F "back_image=@card_back.jpg"

# Test analysis (replace SESSION_ID)
curl -X POST "https://your-app.up.railway.app/grade?session_id=SESSION_ID"
```

### Viewing Detailed Logs

The backend now includes detailed logging:
- Upload events
- Analysis start/completion
- Error stack traces
- Grade results

Check Railway logs for entries like:
```
INFO - Upload started - Session ID: xxx
INFO - Analysis started - Session ID: xxx
ERROR - Analysis error - Session ID: xxx
```

## Performance Optimization

### Image Size Recommendations
- Max resolution: 2000x2000 pixels
- Format: JPEG with 85% quality
- File size: < 2MB per image

### Railway Plan Recommendations
- **Hobby Plan**: Good for testing (512MB RAM)
- **Pro Plan**: Recommended for production (1GB+ RAM)

## Monitoring

Set up monitoring in Railway:
1. Enable health checks (already configured)
2. Set up alerts for deployment failures
3. Monitor memory usage

## Local Testing

Test the Docker container locally before deploying:

```bash
cd backend

# Build
docker build -t pregrader-backend .

# Run
docker run -p 8000:8000 \
  -e POKEMON_TCG_API_KEY=your_key \
  pregrader-backend

# Test
curl http://localhost:8000/health
```

## Support

If issues persist:
1. Check Railway status page
2. Review full error logs
3. Test with the startup_check.py script locally
4. Verify all dependencies in requirements.txt are compatible
