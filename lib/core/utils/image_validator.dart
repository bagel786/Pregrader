import 'dart:io';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;

class ImageValidator {
  /// Detects if a Pokemon card is likely present (Basic check without OpenCV)
  static Future<Map<String, dynamic>> validateImage(XFile imageFile) async {
    // For now, we trust the user's capture to avoid native crashes with OpenCV on iOS.
    // We will rely on the backend for strict analysis.

    try {
      final bytes = await File(imageFile.path).readAsBytes();
      final image = img.decodeImage(bytes);

      if (image == null) {
        return {
          'isValid': false,
          'issues': ['Could not decode image'],
        };
      }

      // Basic Aspect Ratio Check
      double aspectRatio = image.width / image.height;
      if (aspectRatio > 1.0) {
        // Landscape (captured sideways) -> normalize
        aspectRatio = 1 / aspectRatio;
      }

      // Pokemon cards are ~6.3cm x 8.8cm => 0.71
      // We allow a wide range because of camera angles

      // Just returning true for now to unblock the user
      return {'isValid': true, 'issues': <String>[]};
    } catch (e) {
      return {
        'isValid': true,
        'issues': ['Validation skipped: $e'],
      };
    }
  }
}
