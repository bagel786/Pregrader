import 'package:flutter/material.dart';
import 'package:pregrader/screens/home_screen.dart';
import 'package:pregrader/screens/camera_capture_screen.dart';

class AppRoutes {
  static const String home = '/';

  static const String cameraCapture = '/camera_capture';

  static Map<String, WidgetBuilder> get routes => {
    home: (context) => const HomeScreen(),
    cameraCapture: (context) => const CameraCaptureScreen(),
  };
}
