import 'package:flutter/material.dart';

class CameraOverlay extends StatelessWidget {
  const CameraOverlay({super.key});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return CustomPaint(
          size: Size(constraints.maxWidth, constraints.maxHeight),
          painter: OverlayPainter(),
        );
      },
    );
  }
}

class OverlayPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = Colors.black54;

    // Draw full screen dimmed background
    // canvas.drawRect(Rect.fromLTWH(0, 0, size.width, size.height), paint);
    // Actually we need to draw a path with a hole

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
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;

    canvas.drawRRect(
      RRect.fromRectAndRadius(overlayRect, const Radius.circular(12)),
      borderPaint,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) {
    return false;
  }
}
