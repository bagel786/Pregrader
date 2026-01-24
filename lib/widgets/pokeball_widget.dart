import 'package:flutter/material.dart';

class PokeballWidget extends StatelessWidget {
  final VoidCallback onTap;
  final double size;

  const PokeballWidget({super.key, required this.onTap, this.size = 200.0});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: CustomPaint(size: Size(size, size), painter: _PokeballPainter()),
    );
  }
}

class _PokeballPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2;

    final paintRed = Paint()
      ..color =
          const Color(0xFF6A1B9A) // Purple top half instead of red
      ..style = PaintingStyle.fill;

    final paintWhite = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.fill;

    final paintBlack = Paint()
      ..color = Colors.black87
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.width * 0.05; // Relative stroke width

    // Draw top half
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      3.14159, // Pi
      3.14159, // Pi
      false,
      paintRed,
    );

    // Draw bottom half
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      0,
      3.14159,
      false,
      paintWhite,
    );

    // Draw border
    canvas.drawCircle(center, radius, paintBlack);

    // Draw center line
    final linePaint = Paint()
      ..color = Colors.black87
      ..strokeWidth = size.width * 0.05
      ..style = PaintingStyle.stroke;

    canvas.drawLine(
      Offset(0, center.dy),
      Offset(size.width, center.dy),
      linePaint,
    );

    // Draw center button outer circle
    final buttonOuterRadius = radius * 0.3;
    final fillPaint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.fill;

    canvas.drawCircle(center, buttonOuterRadius, fillPaint);
    canvas.drawCircle(center, buttonOuterRadius, paintBlack);

    // Draw center button inner circle
    final buttonInnerRadius = radius * 0.15;
    final innerButtonPaint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.fill;

    final innerButtonBorderPaint = Paint()
      ..color = Colors.black54
      ..style = PaintingStyle.stroke
      ..strokeWidth = size.width * 0.015;

    canvas.drawCircle(center, buttonInnerRadius, innerButtonPaint);
    canvas.drawCircle(center, buttonInnerRadius, innerButtonBorderPaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
