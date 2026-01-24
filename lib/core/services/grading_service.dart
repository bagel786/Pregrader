import 'dart:typed_data';

import 'package:opencv_dart/opencv_dart.dart' as cv;
import 'package:pregrader/core/models/grade_result.dart';

class GradingService {
  /// Entry point to grade an image bytes.
  /// [imageBytes] should be the raw bytes of the image file (e.g. JPG/PNG).
  Future<GradeResult> gradeImage(Uint8List imageBytes) async {
    // 1. Decode image to get dimensions and raw data
    // Note: opencv_dart might prefer direct usage of imdecode from bytes if valid format
    // For now we assume standard image formats.

    final mat = cv.imdecode(imageBytes, cv.IMREAD_COLOR);
    // return GradeResult(centeringScore: 5.0);

    try {
      // 2. Detect Card (Perspective Transform)
      final cardMat = _detectAndWarpCard(mat);

      if (cardMat == null) {
        throw Exception("Could not detect card in image");
      }

      // 3. Calculate Centering
      final centeringScore = _calculateCentering(cardMat);

      return GradeResult(centeringScore: centeringScore);
    } finally {
      // Always dispose standard Mat objects to free native memory
      mat.dispose();
    }
  }

  /// Detects the largest quadrilateral and warps perspective to a flat standard card size.
  cv.Mat? _detectAndWarpCard(cv.Mat input) {
    // 1. Preprocessing
    final gray = cv.cvtColor(input, cv.COLOR_BGR2GRAY);
    final blurred = cv.gaussianBlur(gray, (5, 5), 0);
    final edges = cv.canny(blurred, 75, 200);

    // 2. Find Contours
    final (contours, _) = cv.findContours(
      edges,
      cv.RETR_EXTERNAL,
      cv.CHAIN_APPROX_SIMPLE,
    );

    // 3. Find Card Contour (Largest 4-sided polygon)
    cv.VecPoint? cardContour;
    double maxArea = 0;

    for (final contour in contours) {
      final area = cv.contourArea(contour);
      if (area < 1000) continue; // Filter small noise

      // Simplify contour
      final peri = cv.arcLength(contour, true);
      final approx = cv.approxPolyDP(contour, 0.02 * peri, true);

      // Check if it's a quadrilateral (has 4 points)
      // VecPoint usually has length property
      if (approx.length == 4) {
        if (area > maxArea) {
          maxArea = area;
          cardContour = approx;
        }
      }
    }

    // Cleanup intermediate images
    gray.dispose();
    blurred.dispose();
    edges.dispose();

    if (cardContour == null) return null;

    // 4. Crop to Bounding Box
    final rect = cv.boundingRect(cardContour);
    return input.region(rect);
  }

  /// Calculates centering based on border detection.
  double _calculateCentering(cv.Mat card) {
    // 1. Convert to HSV to detect yellow borders common in Pokemon cards
    // Or just use edge detection on the cropped card to find the "inner" art box.

    // Simple heuristic: Edge detection again on the cropped card.
    // The first strong edge from Top/Bottom/Left/Right is the border.

    final gray = cv.cvtColor(card, cv.COLOR_BGR2GRAY);
    final edges = cv.canny(gray, 50, 150);

    final int h = edges.rows;
    final int w = edges.cols;
    final int midX = w ~/ 2;
    final int midY = h ~/ 2;

    // Scan Top
    int topDist = 0;
    for (int y = 0; y < midY; y++) {
      if (edges.at<int>(y, midX) > 0) {
        topDist = y;
        break;
      }
    }

    // Scan Bottom
    int bottomDist = 0;
    for (int y = h - 1; y > midY; y--) {
      if (edges.at<int>(y, midX) > 0) {
        bottomDist = h - 1 - y;
        break;
      }
    }

    // Scan Left
    int leftDist = 0;
    for (int x = 0; x < midX; x++) {
      if (edges.at<int>(midY, x) > 0) {
        leftDist = x;
        break;
      }
    }

    // Scan Right
    int rightDist = 0;
    for (int x = w - 1; x > midX; x--) {
      if (edges.at<int>(midY, x) > 0) {
        rightDist = w - 1 - x;
        break;
      }
    }

    gray.dispose();
    edges.dispose();

    // Avoid division by zero
    if (topDist + bottomDist == 0 || leftDist + rightDist == 0) {
      return 5.0; // Fail safe
    }

    // Calculate Ratios (e.g. 60/40)
    final topBottomRatio = topDist < bottomDist
        ? topDist / (topDist + bottomDist)
        : bottomDist / (topDist + bottomDist);

    final leftRightRatio = leftDist < rightDist
        ? leftDist / (leftDist + rightDist)
        : rightDist / (leftDist + rightDist);

    // Perfect is 0.5. Worst is 0.0.
    // Score logic: 10 if ratio is 0.45-0.55. Drop off otherwise.
    // Simplified Map: 0.5 -> 10, 0.4 -> 9, 0.3 -> 7...

    double scoreTB = (topBottomRatio / 0.5) * 10;
    double scoreLR = (leftRightRatio / 0.5) * 10;

    if (scoreTB > 10) scoreTB = 10;
    if (scoreLR > 10) scoreLR = 10;

    return (scoreTB + scoreLR) / 2;
  }
}
