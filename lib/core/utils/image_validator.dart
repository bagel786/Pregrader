import 'dart:io';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;

class ImageValidator {
  /// Detects if a Pokemon card is likely present based on aspect ratio
  /// Pokemon cards are approximately 6.3cm x 8.8cm => aspect ratio ~0.716
  static Future<Map<String, dynamic>> validateImage(XFile imageFile) async {
    try {
      final bytes = await File(imageFile.path).readAsBytes();
      final image = img.decodeImage(bytes);

      if (image == null) {
        return {
          'isValid': false,
          'cardDetected': false,
          'issues': ['Could not decode image'],
        };
      }

      // Calculate aspect ratio
      double aspectRatio = image.width / image.height;
      
      // Normalize to portrait orientation
      if (aspectRatio > 1.0) {
        aspectRatio = 1 / aspectRatio;
      }

      // Pokemon card aspect ratio is ~0.716 (2.5" x 3.5")
      // We allow a reasonable range: 0.60 to 0.80
      // This is lenient enough to account for camera angles but strict enough
      // to catch obvious non-card shapes
      const double minAspectRatio = 0.60;
      const double maxAspectRatio = 0.80;
      const double idealAspectRatio = 0.716;

      final bool cardDetected = aspectRatio >= minAspectRatio && 
                                aspectRatio <= maxAspectRatio;

      final List<String> issues = [];

      if (!cardDetected) {
        if (aspectRatio < minAspectRatio) {
          issues.add('Image appears too narrow. Please ensure the card fills the frame.');
        } else if (aspectRatio > maxAspectRatio) {
          issues.add('Image appears too wide. Please ensure the card fills the frame.');
        }
      } else {
        // Card detected, but check if it's close to ideal
        final double deviation = (aspectRatio - idealAspectRatio).abs();
        if (deviation > 0.05) {
          issues.add('Card detected, but framing could be improved for best results.');
        }
      }

      // Check image resolution
      final int minDimension = image.width < image.height ? image.width : image.height;
      if (minDimension < 500) {
        issues.add('Image resolution is low. Try moving closer to the card.');
      }

      return {
        'isValid': cardDetected && issues.isEmpty,
        'cardDetected': cardDetected,
        'aspectRatio': aspectRatio,
        'issues': issues,
      };
    } catch (e) {
      return {
        'isValid': false,
        'cardDetected': false,
        'issues': ['Validation error: $e'],
      };
    }
  }

  /// Quick check for real-time feedback (less strict)
  static bool quickCardCheck(int width, int height) {
    double aspectRatio = width / height;
    
    if (aspectRatio > 1.0) {
      aspectRatio = 1 / aspectRatio;
    }

    // More lenient range for real-time feedback
    return aspectRatio >= 0.55 && aspectRatio <= 0.85;
  }
}
