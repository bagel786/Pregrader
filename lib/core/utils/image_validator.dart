import 'dart:io';
import 'package:camera/camera.dart';
import 'package:image/image.dart' as img;

class ImageValidator {
  /// Validates that an image likely contains a Pokemon card.
  ///
  /// Returns a map with:
  ///   - `cardDetected` (bool): whether the image shape matches a card
  ///   - `isValid` (bool): true when cardDetected AND resolution is adequate (hard blocks)
  ///   - `hasWarnings` (bool): true when cardDetected but framing could be improved (soft warnings)
  ///   - `warnings` (`List<String>`): soft advisory messages
  ///   - `issues` (`List<String>`): hard blocking issues
  static Future<Map<String, dynamic>> validateImage(XFile imageFile) async {
    try {
      final bytes = await File(imageFile.path).readAsBytes();
      final decoded = img.decodeImage(bytes);

      if (decoded == null) {
        return {
          'isValid': false,
          'cardDetected': false,
          'hasWarnings': false,
          'issues': ['Could not decode image'],
          'warnings': <String>[],
        };
      }

      // Apply EXIF rotation so width/height match portrait orientation
      final image = img.bakeOrientation(decoded);

      // Calculate aspect ratio, normalized to portrait
      double aspectRatio = image.width / image.height;
      if (aspectRatio > 1.0) aspectRatio = 1 / aspectRatio;

      // Pokemon card is exactly 0.716 (2.5" × 3.5").
      // Tight range accounts for minor camera angle distortion.
      const double minAspectRatio = 0.67;
      const double maxAspectRatio = 0.76;
      const double idealAspectRatio = 0.716;

      final bool cardDetected =
          aspectRatio >= minAspectRatio && aspectRatio <= maxAspectRatio;

      final List<String> issues = [];    // blocking — card probably not present
      final List<String> warnings = []; // advisory — card detected but could be better

      if (!cardDetected) {
        if (aspectRatio < minAspectRatio) {
          issues.add('No card detected — image appears too narrow. Ensure the card fills the frame.');
        } else {
          issues.add('No card detected — image appears too wide. Ensure the card fills the frame.');
        }
      } else {
        // Soft framing warning
        final double deviation = (aspectRatio - idealAspectRatio).abs();
        if (deviation > 0.03) {
          warnings.add('Framing could be improved — hold the camera directly above the card for best results.');
        }
      }

      // Resolution check — hard block: too low for reliable damage detection
      final int minDimension = image.width < image.height ? image.width : image.height;
      if (minDimension < 600) {
        issues.add('Image resolution is too low ($minDimension px). Move closer to the card.');
      } else if (minDimension < 900) {
        warnings.add('Higher resolution will improve grading accuracy — consider moving closer.');
      }

      // isValid = no hard blocking issues detected
      final bool isValid = cardDetected && issues.isEmpty;
      final bool hasWarnings = warnings.isNotEmpty;

      return {
        'isValid': isValid,
        'cardDetected': cardDetected,
        'hasWarnings': hasWarnings,
        'aspectRatio': aspectRatio,
        'resolution': minDimension,
        'issues': issues,
        'warnings': warnings,
      };
    } catch (e) {
      return {
        'isValid': false,
        'cardDetected': false,
        'hasWarnings': false,
        'issues': ['Validation error: $e'],
        'warnings': <String>[],
      };
    }
  }

  /// Quick check for real-time camera preview feedback (lenient).
  static bool quickCardCheck(int width, int height) {
    double aspectRatio = width / height;
    if (aspectRatio > 1.0) aspectRatio = 1 / aspectRatio;
    return aspectRatio >= 0.62 && aspectRatio <= 0.80;
  }
}
