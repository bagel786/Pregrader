import 'package:flutter/material.dart';

enum CameraReadiness { notReady, nearReady, ready }

class CameraOverlay extends StatelessWidget {
  final CameraReadiness readiness;
  final String hint;

  const CameraOverlay({
    super.key,
    this.readiness = CameraReadiness.notReady,
    this.hint = 'Align card within the frame',
  });

  Color get _borderColor {
    switch (readiness) {
      case CameraReadiness.ready:
        return Colors.green;
      case CameraReadiness.nearReady:
        return Colors.orange;
      case CameraReadiness.notReady:
        return Colors.red;
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return Stack(
          children: [
            CustomPaint(
              size: Size(constraints.maxWidth, constraints.maxHeight),
              painter: OverlayPainter(borderColor: _borderColor),
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
                    hint,
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
  }
}

class OverlayPainter extends CustomPainter {
  final Color borderColor;

  const OverlayPainter({required this.borderColor});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = Colors.black54;

    // Standard card aspect ratio: 2.5/3.5 = ~0.714
    final cardWidth = size.width * 0.85;
    final cardHeight = cardWidth / 0.714;

    final centerX = size.width / 2;
    final centerY = size.height / 2;

    final overlayRect = Rect.fromCenter(
      center: Offset(centerX, centerY),
      width: cardWidth,
      height: cardHeight,
    );

    // Create a path for the whole screen
    final path = Path()..addRect(Rect.fromLTWH(0, 0, size.width, size.height));

    // Create a path for the cutout (card)
    final cutoutPath = Path()
      ..addRRect(
        RRect.fromRectAndRadius(overlayRect, const Radius.circular(12)),
      );

    // Combine them (Difference)
    final pathWithCutout = Path.combine(
      PathOperation.difference,
      path,
      cutoutPath,
    );

    canvas.drawPath(pathWithCutout, paint);

    // Draw border around the cutout
    final borderPaint = Paint()
      ..color = borderColor
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;

    canvas.drawRRect(
      RRect.fromRectAndRadius(overlayRect, const Radius.circular(12)),
      borderPaint,
    );

    // Draw corner indicators
    _drawCornerIndicators(canvas, overlayRect, borderColor);
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
    return oldDelegate.borderColor != borderColor;
  }
}
