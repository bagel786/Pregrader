import 'package:flutter/material.dart';

class AppTheme {
  // Define custom colors directly if needed, or use ColorScheme
  static const Color _primaryColor = Color(0xFF6A1B9A); // Deep Purple
  static const Color _secondaryColor = Color(0xFFE1BEE7); // Light Purple
  static const Color _surfaceLight = Colors.white;
  static const Color _surfaceDark = Color(0xFF1E1E1E);

  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.fromSeed(
        seedColor: _primaryColor,
        secondary: _secondaryColor,
        surface: Colors.white,
      ),
      scaffoldBackgroundColor: _surfaceLight,
      appBarTheme: const AppBarTheme(
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.transparent, // Or colored if preferred
        foregroundColor: Colors.black,
      ),
    );
  }

  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: _primaryColor,
        secondary: _secondaryColor,
        brightness: Brightness.dark,
        surface: Color(0xFF2C2C2C),
      ),
      scaffoldBackgroundColor: _surfaceDark,
      appBarTheme: const AppBarTheme(
        centerTitle: true,
        elevation: 0,
        backgroundColor: Colors.transparent,
        foregroundColor: Colors.white,
      ),
    );
  }
}
