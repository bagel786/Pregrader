# iOS Build Guide - Run Without Cable

To run your app on iPhone without keeping it connected, you need to build a "Release" or "Profile" build with proper code signing.

## Prerequisites

1. **Apple Developer Account** (Required)
   - Free account: 7-day certificate (app expires after 7 days)
   - Paid account ($99/year): 1-year certificate
   - Sign up at: https://developer.apple.com

2. **Xcode** (Required)
   - Install from Mac App Store
   - Open Xcode at least once to accept license

3. **Physical iPhone** connected via USB

## Option 1: Quick Build (Free Account - 7 Days)

### Step 1: Configure Signing in Xcode
```bash
# Open the iOS project in Xcode
cd ios
open Runner.xcworkspace
```

In Xcode:
1. Select "Runner" in the left sidebar
2. Go to "Signing & Capabilities" tab
3. Check "Automatically manage signing"
4. Select your Apple ID team
5. Change Bundle Identifier to something unique (e.g., `com.yourname.pregrader`)

### Step 2: Build and Install
```bash
# Go back to project root
cd ..

# Build in profile mode (optimized but with debugging)
flutter build ios --release

# Or use Xcode to build and run
# In Xcode: Product > Run (or Cmd+R)
```

### Step 3: Trust Developer on iPhone
1. On iPhone: Settings > General > VPN & Device Management
2. Tap your Apple ID
3. Tap "Trust [Your Apple ID]"

### Step 4: Disconnect and Run
- App will now run without cable for 7 days
- After 7 days, reconnect and rebuild

## Option 2: TestFlight (Paid Account - Recommended)

TestFlight allows you to distribute to yourself and testers without cable.

### Step 1: Create App in App Store Connect
1. Go to https://appstoreconnect.apple.com
2. Click "My Apps" > "+" > "New App"
3. Fill in app information
4. Note your Bundle ID

### Step 2: Configure App
```bash
# Update pubspec.yaml version
version: 1.0.0+1

# Update Bundle ID in Xcode (see Option 1, Step 1)
```

### Step 3: Build Archive
```bash
# Build for release
flutter build ios --release

# Open in Xcode
cd ios
open Runner.xcworkspace
```

In Xcode:
1. Select "Any iOS Device (arm64)" as target
2. Product > Archive
3. Wait for build to complete
4. Click "Distribute App"
5. Select "App Store Connect"
6. Follow prompts to upload

### Step 4: TestFlight Distribution
1. Go to App Store Connect
2. Select your app > TestFlight tab
3. Add yourself as internal tester
4. Install TestFlight app on iPhone
5. Accept invitation and install app

**Benefits:**
- No cable needed
- App doesn't expire
- Easy updates
- Can share with testers

## Option 3: Ad Hoc Distribution (Paid Account)

For specific devices without TestFlight.

### Step 1: Register Device UDID
1. Connect iPhone to Mac
2. Open Finder > iPhone > Click serial number to show UDID
3. Copy UDID
4. Go to https://developer.apple.com
5. Certificates, IDs & Profiles > Devices > "+"
6. Add device with UDID

### Step 2: Create Provisioning Profile
1. In developer.apple.com
2. Profiles > "+" > Ad Hoc
3. Select your App ID
4. Select your certificate
5. Select registered devices
6. Download profile

### Step 3: Build with Profile
```bash
# Build with ad hoc profile
flutter build ipa --export-options-plist=ios/ExportOptions.plist
```

### Step 4: Install via Xcode
1. Window > Devices and Simulators
2. Select your iPhone
3. Click "+" under Installed Apps
4. Select the .ipa file from `build/ios/ipa/`

## Quick Comparison

| Method | Cost | Duration | Cable Needed | Best For |
|--------|------|----------|--------------|----------|
| Free Account | Free | 7 days | Initial install only | Quick testing |
| TestFlight | $99/year | Permanent | Never | Production/Testing |
| Ad Hoc | $99/year | 1 year | Initial install only | Specific devices |

## Troubleshooting

### "Untrusted Developer"
- Settings > General > VPN & Device Management > Trust

### "Unable to Install"
- Check Bundle ID is unique
- Verify signing certificate is valid
- Try cleaning: `flutter clean && flutter pub get`

### Build Fails
```bash
# Clean everything
flutter clean
cd ios
rm -rf Pods Podfile.lock
pod install
cd ..
flutter pub get
flutter build ios --release
```

### Certificate Expired
- Free account: Reconnect and rebuild every 7 days
- Paid account: Renew certificate in developer.apple.com

## Recommended Workflow

**For Development:**
1. Use free account with 7-day builds
2. Rebuild weekly while developing

**For Production:**
1. Get paid developer account ($99/year)
2. Use TestFlight for yourself and testers
3. Submit to App Store when ready

## Next Steps

After building:
1. Test the app thoroughly on device
2. Check that backend connection works (Railway URL)
3. Verify camera permissions work
4. Test grading flow end-to-end

Need help? Check:
- Flutter iOS deployment: https://docs.flutter.dev/deployment/ios
- Apple Developer docs: https://developer.apple.com/documentation/
