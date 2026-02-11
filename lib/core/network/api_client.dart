import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  late final Dio dio;

  factory ApiClient() {
    return _instance;
  }

  ApiClient._internal() {
    dio = Dio(
      BaseOptions(
        baseUrl: _getBaseUrl(),
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 30),
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
      ),
    );

    if (kDebugMode) {
      dio.interceptors.add(
        LogInterceptor(requestBody: true, responseBody: true),
      );
    }
  }

  String _getBaseUrl() {
    // Production URL (Railway)
    const productionUrl = 'https://pregrader-production.up.railway.app';
    
    // Use production in release mode
    if (kReleaseMode) {
      return productionUrl;
    }
    
    // Development URLs
    if (kIsWeb) return 'http://localhost:8000';

    if (Platform.isAndroid) {
      // Android Emulator localhost
      return 'http://10.0.2.2:8000';
    } else if (Platform.isIOS) {
      // Use LAN IP for Physical Device to access backend
      // For production, this will use Railway URL
      return 'http://192.168.68.159:8000';
    }

    // Default fallback
    return 'http://192.168.68.159:8000';
  }
}
