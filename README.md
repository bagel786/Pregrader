# Pokemon Card Pregrader

A mobile application for pre-grading Pokemon trading cards using computer vision and image analysis. Built with Flutter for the frontend and FastAPI (Python) for the backend.

## Overview

Pokemon Card Pregrader helps collectors estimate the condition grade of their Pokemon cards before sending them to professional grading services like PSA. The app analyzes card photos and evaluates:

- **Centering**: Card alignment and border ratios
- **Corners**: Corner wear and damage detection
- **Edges**: Edge wear and whitening analysis
- **Surface**: Scratches, dents, and surface damage

## Features

- 📸 Guided camera capture with overlay alignment
- 🔍 Automated card quality analysis
- 📊 PSA-style grade estimation (1-10 scale)
- 🎯 Detailed breakdown of grading factors
- 🔄 Front and back card analysis
- 📱 Native iOS and Android support
- 🌐 Pokemon TCG API integration for card lookup

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
│   │   ├── home_screen.dart
│   │   ├── camera_capture_screen.dart
│   │   ├── review_screen.dart
│   │   └── result_screen.dart
│   ├── services/            # Business logic services
│   └── widgets/             # Reusable UI components
│
├── backend/                  # Python backend
│   ├── analysis/            # Card analysis modules
│   │   ├── centering.py     # Centering analysis
│   │   ├── corners.py       # Corner wear detection
│   │   ├── edges.py         # Edge wear analysis
│   │   ├── surface.py       # Surface damage detection
│   │   ├── scoring.py       # Grade calculation engine
│   │   └── vision/          # Image preprocessing
│   ├── api/                 # API endpoints
│   │   ├── combined_grading.py
│   │   └── session_manager.py
│   ├── services/            # External services
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

4. Create a `.env` file (optional):
```bash
cp .env.example .env
```

5. Start the backend server:
```bash
python main.py
```

The API will be available at `http://localhost:8000`

### Frontend Setup

1. Install Flutter dependencies:
```bash
flutter pub get
```

2. Create a `.env` file in the root directory:
```
API_BASE_URL=http://localhost:8000
```

3. Run the app:
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

#### Card Search & Info
- `GET /cards/search?q={name}` - Search for Pokemon cards
- `GET /cards/{card_id}` - Get card details by ID
- `GET /sets` - Get all Pokemon card sets

#### Grading Workflow
- `POST /api/grading/start` - Start a new grading session
- `POST /api/grading/{session_id}/upload-front` - Upload front image
- `POST /api/grading/{session_id}/upload-back` - Upload back image
- `GET /api/grading/{session_id}/result` - Get grading results

#### Legacy Endpoints
- `POST /analyze/upload` - Upload both images at once
- `POST /analyze/{session_id}` - Run analysis
- `GET /analyze/{session_id}/results` - Get cached results

## Usage

1. **Launch the app** and accept camera permissions
2. **Read the disclaimer** about grading accuracy
3. **Capture front photo** using the guided overlay
4. **Capture back photo** (optional but recommended)
5. **Review photos** before submission
6. **View results** with detailed grade breakdown

## Grading Algorithm

The app uses a multi-factor analysis approach:

1. **Centering (15% weight)**: Analyzes border ratios (left/right, top/bottom)
2. **Corners (30% weight)**: Detects wear, whitening, and damage on all four corners
3. **Edges (25% weight)**: Evaluates edge condition and whitening
4. **Surface (30% weight)**: Identifies scratches, dents, and surface imperfections

Final grade is calculated using a weighted average and mapped to PSA's 1-10 scale.

## Development

### Running Tests

```bash
# Flutter tests
flutter test

# Backend tests
cd backend
python -m pytest
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
2. Railway will auto-detect the `backend/` directory
3. Environment variables are configured via Railway dashboard
4. See `backend/RAILWAY_DEPLOYMENT.md` for details

### Mobile App Distribution

- **iOS**: TestFlight or App Store via Xcode
- **Android**: Google Play Console or direct APK distribution
- App has not been published to stores yet, updates coming soon!

## Troubleshooting

See `TROUBLESHOOTING_500_ERROR.md` for common backend issues.

### Common Issues

**Camera not working**
- Ensure camera permissions are granted
- Check Info.plist (iOS) and AndroidManifest.xml (Android) for permission declarations

**API connection failed**
- Verify backend is running on correct port
- Check `.env` file has correct API_BASE_URL
- For iOS simulator, use `http://localhost:8000`
- For Android emulator, use `http://10.0.2.2:8000`

**Image quality too low**
- Ensure good lighting conditions
- Keep card flat and in focus
- Use the overlay guide for proper alignment

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
- Flutter team for the amazing framework

## Contact

For questions or support, please open an issue in the repository.

---

**Note**: This is a pre-grading tool for estimation purposes only. Professional grading services may have different standards and results may vary.
