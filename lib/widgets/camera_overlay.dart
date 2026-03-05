import 'package:flutter/material.dart';

/// Standard Pokemon card aspect ratio: 2.5" × 3.5" ≈ 0.714
const double _cardAspectRatio = 0.714;

/// Card frame occupies 85% of screen width
const double _cardFrameWidthRatio = 0.85;

const _cardCornerRadius = Radius.circular(12);

enum CameraReadiness { notReady, nearReady, ready }

class CameraOverlay extends StatefulWidget {
  final CameraReadiness readiness;
  final String hint;
  /// Detected card rect in normalized coordinates (0.0–1.0).
  /// null means no card detected — show static guide.
  final Rect? detectedCard;

  const CameraOverlay({
    super.key,
    this.readiness = CameraReadiness.notReady,
    this.hint = 'Align card within the frame',
    this.detectedCard,
  });

  @override
  State<CameraOverlay> createState() => _CameraOverlayState();
}

class _CameraOverlayState extends State<CameraOverlay>
    with SingleTickerProviderStateMixin {
  late AnimationController _animController;
  Rect? _previousRect;
  Rect? _targetRect;

  Color get _borderColor {
    switch (widget.readiness) {
      case CameraReadiness.ready:
        return Colors.green;
      case CameraReadiness.nearReady:
        return Colors.orange;
      case CameraReadiness.notReady:
        return Colors.red;
    }
  }

  @override
  void initState() {
    super.initState();
    _animController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 200),
    );
    _targetRect = widget.detectedCard;
  }

  @override
  void didUpdateWidget(CameraOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.detectedCard != widget.detectedCard) {
      _previousRect = oldWidget.detectedCard;
      _targetRect = widget.detectedCard;
      _animController.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _animController.dispose();
    super.dispose();
  }

  Rect? get _animatedRect {
    if (_previousRect == null && _targetRect == null) return null;
    if (_previousRect == null) return _targetRect;
    if (_targetRect == null) {
      // Animating from detected → static guide (return null to let painter use guide)
      return _animController.isCompleted ? null : _previousRect;
    }
    return Rect.lerp(_previousRect, _targetRect, _animController.value);
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animController,
      builder: (context, _) {
        return LayoutBuilder(
          builder: (context, constraints) {
            return Stack(
              children: [
                CustomPaint(
                  size: Size(constraints.maxWidth, constraints.maxHeight),
                  painter: OverlayPainter(
                    borderColor: _borderColor,
                    detectedCard: _animatedRect,
                  ),
                ),
                // Dynamic hint text
                Positioned(
                  bottom: 120,
                  left: 0,
                  right: 0,
                  child: Center(
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        widget.hint,
                        style: TextStyle(
                          color: _borderColor,
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            );
          },
        );
      },
    );
  }
}

/// Returns the static guide rect for a given screen size.
/// Used by both the overlay painter and the crop fallback.
Rect staticGuideRect(Size size) {
  final cardWidth = size.width * _cardFrameWidthRatio;
  final cardHeight = cardWidth / _cardAspectRatio;
  return Rect.fromCenter(
    center: Offset(size.width / 2, size.height / 2),
    width: cardWidth,
    height: cardHeight,
  );
}

class OverlayPainter extends CustomPainter {
  final Color borderColor;
  final Rect? detectedCard;

  const OverlayPainter({required this.borderColor, this.detectedCard});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = Colors.black54;

    // Static guide rect (always shown faintly as reference)
    final guideRect = staticGuideRect(size);

    // Active rect: detected card or static guide
    final Rect activeRect;
    if (detectedCard != null) {
      activeRect = Rect.fromLTRB(
        detectedCard!.left * size.width,
        detectedCard!.top * size.height,
        detectedCard!.right * size.width,
        detectedCard!.bottom * size.height,
      );
    } else {
      activeRect = guideRect;
    }

    // Dark mask with cutout around active rect
    final path = Path()..addRect(Rect.fromLTWH(0, 0, size.width, size.height));
    final cutoutPath = Path()
      ..addRRect(
        RRect.fromRectAndRadius(activeRect, _cardCornerRadius),
      );
    final pathWithCutout = Path.combine(
      PathOperation.difference,
      path,
      cutoutPath,
    );
    canvas.drawPath(pathWithCutout, paint);

    // Draw faint static guide when card is detected (so user sees the reference)
    if (detectedCard != null) {
      final guidePaint = Paint()
        ..color = Colors.white.withValues(alpha: 0.15)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1;
      canvas.drawRRect(
        RRect.fromRectAndRadius(guideRect, _cardCornerRadius),
        guidePaint,
      );
    }

    // Draw border around active rect
    final borderPaint = Paint()
      ..color = borderColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    canvas.drawRRect(
      RRect.fromRectAndRadius(activeRect, _cardCornerRadius),
      borderPaint,
    );

    // Draw corner indicators on active rect
    _drawCornerIndicators(canvas, activeRect, borderColor);
  }

  void _drawCornerIndicators(Canvas canvas, Rect rect, Color color) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round;

    const cornerLength = 20.0;

    // Top-left
    canvas.drawLine(
      Offset(rect.left, rect.top + cornerLength),
      Offset(rect.left, rect.top),
      paint,
    );
    canvas.drawLine(
      Offset(rect.left, rect.top),
      Offset(rect.left + cornerLength, rect.top),
      paint,
    );

    // Top-right
    canvas.drawLine(
      Offset(rect.right - cornerLength, rect.top),
      Offset(rect.right, rect.top),
      paint,
    );
    canvas.drawLine(
      Offset(rect.right, rect.top),
      Offset(rect.right, rect.top + cornerLength),
      paint,
    );

    // Bottom-left
    canvas.drawLine(
      Offset(rect.left, rect.bottom - cornerLength),
      Offset(rect.left, rect.bottom),
      paint,
    );
    canvas.drawLine(
      Offset(rect.left, rect.bottom),
      Offset(rect.left + cornerLength, rect.bottom),
      paint,
    );

    // Bottom-right
    canvas.drawLine(
      Offset(rect.right - cornerLength, rect.bottom),
      Offset(rect.right, rect.bottom),
      paint,
    );
    canvas.drawLine(
      Offset(rect.right, rect.bottom),
      Offset(rect.right, rect.bottom - cornerLength),
      paint,
    );
  }

  @override
  bool shouldRepaint(covariant OverlayPainter oldDelegate) {
    return oldDelegate.borderColor != borderColor ||
        oldDelegate.detectedCard != detectedCard;
  }
}
