# Pokemon Card Pregrader

A mobile application for pre-grading Pokemon trading cards using hybrid AI-powered detection and computer vision. Built with Flutter for the frontend and FastAPI (Python) for the backend.

## Overview

Pokemon Card Pregrader helps collectors estimate the condition grade of their Pokemon cards before sending them to professional grading services like PSA. The app uses a hybrid detection system combining traditional computer vision (OpenCV) with AI-powered analysis (Claude Vision API) to achieve 95%+ detection success rate.

### Key Features

- 📸 Guided camera capture with overlay alignment
- 🤖 **Hybrid AI Detection**: Combines fast OpenCV with intelligent AI fallback
- 🔍 Automated card quality analysis with 95%+ success rate
- 📊 PSA-style grade estimation (1-10 scale)
- 🎯 Detailed breakdown of grading factors
- 🔄 Front and back card analysis
- 🖼️ Visual debugging to see exactly what was detected
- 📱 Native iOS and Android support
- 🌐 Pokemon TCG API integration for card lookup

## What's New - Hybrid Detection System

The app now uses an intelligent hybrid approach for card detection:

1. **Fast Path (70% of images)**: Tries OpenCV first (~30ms, free)
2. **AI Fallback (30% of images)**: Uses Claude Vision API for difficult cases (~2-3s, ~$0.01)
3. **Enhanced Corner Detection**: Filters 50-70% of false positives
4. **Visual Debugging**: See exactly what was detected

**Benefits:**
- ✅ 95% detection success rate (up from 75%)
- ✅ Works on any background (wood, carpet, fabric, etc.)
- ✅ Handles angled cards (up to 45° rotation)
- ✅ Accurate corner detection with false positive filtering
- ✅ Cost-efficient (~$0.006 per grading)

## Grading Analysis

The app evaluates four key factors:

- **Centering**: Card alignment and border ratios
- **Corners**: Corner wear and damage detection (with enhanced validation)
- **Edges**: Edge wear and whitening analysis
- **Surface**: Scratches, dents, and surface damage

## Tech Stack

### Frontend (Mobile App)
- **Flutter** 3.10.7+
- **Dart** SDK
- **Dependencies**:
  - `camera` - Camera access and capture
  - `dio` - HTTP client for API calls
  - `image` - Image processing
  - `permission_handler` - Camera permissions
  - `path_provider` - File system access

### Backend (API Server)
- **FastAPI** - Modern Python web framework
- **OpenCV** - Computer vision and image analysis
- **Claude Vision API** - AI-powered card detection
- **NumPy** - Numerical computations
- **httpx** - Async HTTP client
- **Python 3.9+**

## Project Structure

```
pregrader/
├── lib/                      # Flutter app source
│   ├── core/                 # Core utilities and config
│   │   ├── models/          # Data models
│   │   ├── network/         # API client
│   │   ├── theme/           # App theming
│   │   └── utils/           # Helper utilities
│   ├── screens/             # App screens
│   ├── services/            # Business logic services
│   └── widgets/             # Reusable UI components
│
├── backend/                  # Python backend
│   ├── analysis/            # Card analysis modules
│   │   ├── centering.py     # Centering analysis
│   │   ├── corners.py       # Corner wear detection
│   │   ├── enhanced_corners.py  # Enhanced corner detection (NEW)
│   │   ├── edges.py         # Edge wear analysis
│   │   ├── surface.py       # Surface damage detection
│   │   ├── scoring.py       # Grade calculation engine
│   │   └── vision/          # Image preprocessing & debugging
│   │       ├── debugger.py  # Visual debugging tool (NEW)
│   │       └── ...
│   ├── api/                 # API endpoints
│   │   ├── combined_grading.py
│   │   ├── enhanced_detection.py  # Hybrid detection endpoints (NEW)
│   │   └── session_manager.py
│   ├── services/            # External services
│   │   ├── ai/              # AI services (NEW)
│   │   │   └── vision_detector.py  # Claude Vision integration
│   │   └── pokemon_tcg.py   # Pokemon TCG API client
│   └── main.py              # FastAPI application
│
├── android/                 # Android platform code
├── ios/                     # iOS platform code
└── test/                    # Test files
```

## Getting Started

### Prerequisites

- Flutter SDK 3.10.7 or higher
- Dart SDK
- Python 3.9 or higher
- iOS Simulator / Android Emulator or physical device
- Xcode (for iOS development)
- Android Studio (for Android development)

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file with your API key:
```bash
# Required for AI detection
ANTHROPIC_API_KEY=your-claude-api-key

# Optional configuration
DEFAULT_DETECTION_METHOD=hybrid
OPENCV_CONFIDENCE_THRESHOLD=0.70
ENABLE_DEBUG_IMAGES=true
```

5. Start the backend server:
```bash
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`

### Frontend Setup

1. Install Flutter dependencies:
```bash
flutter pub get
```

2. Run the app:
```bash
# iOS
flutter run -d ios

# Android
flutter run -d android

# Or select device interactively
flutter run
```

## API Documentation

Once the backend is running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Key Endpoints

#### V2 API (Hybrid Detection - Recommended)
- `POST /api/v2/grading/start` - Start a new grading session
- `POST /api/v2/grading/{session_id}/upload-front` - Upload front with hybrid detection
- `POST /api/v2/grading/{session_id}/upload-back` - Upload back with hybrid detection
- `GET /api/v2/grading/{session_id}/result` - Get grading results
- `GET /api/v2/debug/{session_id}/visualization` - View debug visualization
- `GET /api/v2/admin/detection-stats` - View detection statistics

#### Card Search & Info
- `GET /cards/search?q={name}` - Search for Pokemon cards
- `GET /cards/{card_id}` - Get card details by ID
- `GET /sets` - Get all Pokemon card sets

## Usage

1. **Launch the app** and accept camera permissions
2. **Read the disclaimer** about grading accuracy
3. **Capture front photo** using the guided overlay
4. **Capture back photo** (optional but recommended)
5. **Review photos** before submission
6. **View results** with detailed grade breakdown

The app automatically uses the hybrid detection system:
- Fast OpenCV detection for easy images
- AI-powered detection for challenging cases
- Enhanced corner analysis with false positive filtering

## Grading Algorithm

The app uses a multi-factor analysis approach:

1. **Centering (25% weight)**: Analyzes border ratios (left/right, top/bottom)
2. **Corners (25% weight)**: Detects wear, whitening, and damage with enhanced validation
3. **Edges (25% weight)**: Evaluates edge condition and whitening
4. **Surface (25% weight)**: Identifies scratches, dents, and surface imperfections

Final grade is calculated using a weighted average with damage penalties, mapped to PSA's 1-10 scale.

## Development

### Running Tests

```bash
# Flutter tests
flutter test

# Backend tests
cd backend
python test_before_deploy.py path/to/test_card.jpg
```

### Building for Production

```bash
# Android APK
flutter build apk --release

# iOS IPA
flutter build ios --release

# Android App Bundle
flutter build appbundle --release
```

## Deployment

### Backend Deployment (Railway)

The backend is configured for Railway deployment:

1. Connect your GitHub repository to Railway
2. Set environment variable: `ANTHROPIC_API_KEY`
3. Railway will auto-detect and deploy
4. See `backend/HYBRID_DETECTION_SETUP.md` for details

### Mobile App Distribution

- **iOS**: TestFlight or App Store via Xcode
- **Android**: Google Play Console or direct APK distribution

## Performance & Costs

### Detection Performance
- **Success Rate**: 95%+ (up from 75%)
- **Average Speed**: ~800ms (30ms for 70% of images, 2-3s for 30%)
- **OpenCV Usage**: 60-70% (fast, free)
- **AI Usage**: 30-40% (slower, paid)

### Cost Analysis
- **Per grading**: ~$0.006 (2 images)
- **100 gradings/day**: ~$18/month
- **500 gradings/day**: ~$90/month
- **1000 gradings/day**: ~$180/month

## Troubleshooting

### Common Issues

**Camera not working**
- Ensure camera permissions are granted
- Check Info.plist (iOS) and AndroidManifest.xml (Android)

**API connection failed**
- Verify backend is running
- Check network connectivity
- For iOS simulator: `http://localhost:8000`
- For Android emulator: `http://10.0.2.2:8000`

**Detection fails**
- View debug visualization at `/api/v2/debug/{session}/visualization`
- Ensure good lighting and card is visible
- Check detection stats at `/api/v2/admin/detection-stats`

**High API costs**
- Adjust `OPENCV_CONFIDENCE_THRESHOLD` to use AI less
- Monitor usage in Anthropic dashboard

## Documentation

- `IMPLEMENTATION_SUMMARY.md` - Hybrid detection overview
- `backend/HYBRID_DETECTION_ARCHITECTURE.md` - Technical architecture
- `DEPLOYMENT_CHECKLIST.md` - Deployment guide
- `QUICK_REFERENCE.md` - Quick reference guide

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is private and proprietary.

## Acknowledgments

- Pokemon TCG API for card data
- OpenCV community for computer vision tools
- Anthropic for Claude Vision API
- Flutter team for the amazing framework

## Contact

For questions or support, please open an issue in the repository.

---

**Note**: This is a pre-grading tool for estimation purposes only. Professional grading services may have different standards and results may vary.
