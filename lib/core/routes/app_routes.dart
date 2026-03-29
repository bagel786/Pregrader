import 'package:flutter/material.dart';
import 'package:pregrader/screens/home_screen.dart';
import 'package:pregrader/screens/document_scan_capture_screen.dart';
import 'package:pregrader/screens/disclaimer_screen.dart';
import 'package:pregrader/screens/privacy_policy_screen.dart';

class AppRoutes {
  static const String home = '/';

  static const String cameraCapture = '/camera_capture';

  static const String disclaimer = '/disclaimer';

  static const String privacyPolicy = '/privacy-policy';

  static Map<String, WidgetBuilder> get routes => {
    home: (context) => const HomeScreen(),
    cameraCapture: (context) => const DocumentScanCaptureScreen(),
    disclaimer: (context) => const DisclaimerScreen(),
    privacyPolicy: (context) => const PrivacyPolicyScreen(),
  };
}
