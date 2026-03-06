import 'package:flutter/services.dart';

/// Native iOS Vision framework rectangle detection via MethodChannel.
/// Returns null on Android or when no rectangle is detected.
class CardDetectorService {
  static const _channel = MethodChannel('com.pregrader/card_detector');

  /// Detect a card rectangle in the image at [imagePath].
  /// Returns a normalized Rect (0–1) or null if not found.
  static Future<CardDetectionResult?> detectRectangle(String imagePath) async {
    try {
      final result = await _channel.invokeMethod<Map>('detectRectangle', {
        'imagePath': imagePath,
      });
      if (result == null) return null;

      final map = Map<String, double>.from(result.cast<String, double>());
      return CardDetectionResult(
        boundingBox: Rect.fromLTRB(
          map['left']!,
          map['top']!,
          map['right']!,
          map['bottom']!,
        ),
        confidence: map['confidence']!,
        topLeft: Offset(map['topLeftX']!, map['topLeftY']!),
        topRight: Offset(map['topRightX']!, map['topRightY']!),
        bottomLeft: Offset(map['bottomLeftX']!, map['bottomLeftY']!),
        bottomRight: Offset(map['bottomRightX']!, map['bottomRightY']!),
      );
    } on MissingPluginException {
      return null;
    } catch (_) {
      return null;
    }
  }

  /// Detect a card rectangle from raw BGRA pixel buffer (live camera frames).
  /// The buffer is in landscape orientation; Vision rotates to portrait internally.
  static Future<CardDetectionResult?> detectRectangleFromBuffer(
    Uint8List bytes,
    int width,
    int height,
    int bytesPerRow,
  ) async {
    try {
      final result = await _channel.invokeMethod<Map>('detectRectangleFromBuffer', {
        'bytes': bytes,
        'width': width,
        'height': height,
        'bytesPerRow': bytesPerRow,
      });
      if (result == null) return null;

      final map = Map<String, double>.from(result.cast<String, double>());
      return CardDetectionResult(
        boundingBox: Rect.fromLTRB(
          map['left']!,
          map['top']!,
          map['right']!,
          map['bottom']!,
        ),
        confidence: map['confidence']!,
        topLeft: Offset(map['topLeftX']!, map['topLeftY']!),
        topRight: Offset(map['topRightX']!, map['topRightY']!),
        bottomLeft: Offset(map['bottomLeftX']!, map['bottomLeftY']!),
        bottomRight: Offset(map['bottomRightX']!, map['bottomRightY']!),
      );
    } on MissingPluginException {
      return null;
    } catch (_) {
      return null;
    }
  }
}

class CardDetectionResult {
  final Rect boundingBox;
  final double confidence;
  final Offset topLeft;
  final Offset topRight;
  final Offset bottomLeft;
  final Offset bottomRight;

  const CardDetectionResult({
    required this.boundingBox,
    required this.confidence,
    required this.topLeft,
    required this.topRight,
    required this.bottomLeft,
    required this.bottomRight,
  });
}
