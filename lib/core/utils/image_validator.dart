import 'package:camera/camera.dart';
import 'package:opencv_dart/opencv_dart.dart' as cv;

class ImageValidator {
  /// Detects if a Pokemon card is present in the image using geometry and color checks.
  /// Returns a map with 'isValid' (bool) and 'issues' (List<String>).
  static Future<Map<String, dynamic>> validateImage(XFile image) async {
    final issues = <String>[];
    String? failureReason;

    try {
      // 1. Read image
      final mat = cv.imread(image.path);
      final height = mat.rows;
      final width = mat.cols;
      final totalArea = width * height;

      // --- COLOR CHECK (Saturation) ---
      // Relaxed Threshold: 30 (was 40) to handle sleeves/dim light
      final hsv = cv.cvtColor(mat, cv.COLOR_BGR2HSV);
      final channels = cv.split(hsv);
      final saturation = channels[1]; // S channel
      final meanSaturation = cv.mean(saturation);

      if (meanSaturation.val1 < 30) {
        issues.add(
          "Image dull (Sat: ${meanSaturation.val1.toStringAsFixed(1)})",
        );
      }

      // --- GEOMETRY CHECK ---
      // 2. Convert to grayscale
      final gray = cv.cvtColor(mat, cv.COLOR_BGR2GRAY);

      // 3. Blur & Canny (Relaxed Lower Threshold)
      final blurred = cv.gaussianBlur(gray, (5, 5), 0);
      final edges = cv.canny(blurred, 30, 100);

      // 4. Find Contours
      final (contours, _) = cv.findContours(
        edges,
        cv.RETR_EXTERNAL,
        cv.CHAIN_APPROX_SIMPLE,
      );

      // 5. Find Largest Card-Like Contour
      bool shapeFound = false;
      double maxArea = 0;
      double bestRatio = 0;

      for (final contour in contours) {
        final perimeter = cv.arcLength(contour, true);
        final approx = cv.approxPolyDP(contour, 0.04 * perimeter, true);

        // Check if roughly rectangular (4 corners)
        if (approx.length == 4) {
          final rect = cv.boundingRect(approx);
          final area = rect.width * rect.height;

          if (area > maxArea) {
            maxArea = area.toDouble();
            bestRatio = rect.width / rect.height;
          }

          // Relaxed: Area > 5% of screen (was 10%)
          if (area < (totalArea * 0.05)) continue;

          final aspectRatio = rect.width / rect.height;

          // Relaxed Range: 0.60 - 0.80 (Portrait)
          // Landscape: 1.25 - 1.66

          bool isPortraitCard = (aspectRatio >= 0.60 && aspectRatio <= 0.80);
          bool isLandscapeCard = (aspectRatio >= 1.25 && aspectRatio <= 1.66);

          if (isPortraitCard || isLandscapeCard) {
            shapeFound = true;
            break;
          }
        }
      }

      if (!shapeFound) {
        // Debug Info added to error message
        failureReason =
            "No card shape. (Area: ${(maxArea / totalArea * 100).toStringAsFixed(1)}%, Ratio: ${bestRatio.toStringAsFixed(2)})";
        issues.add(failureReason!);
      } else if (issues.isNotEmpty) {
        // If shape found but color bad
        failureReason = "Card shape found, but quality check failed.";
      }
    } catch (e) {
      print("OpenCV Error: $e");
      issues.add("Processing error ($e)");
    }

    bool isValid = issues.isEmpty;

    return {'isValid': isValid, 'issues': issues};
  }
}
