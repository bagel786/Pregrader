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
    if (kIsWeb) return 'http://localhost:8000';

    if (Platform.isAndroid) {
      // Android Emulator localhost
      return 'http://10.0.2.2:8000';
    } else if (Platform.isIOS) {
      // Use LAN IP for Physical Device to access backend
      // TODO: Replace with hosted URL for production
      return 'http://192.168.68.159:8000';
    }

    // Default fallback
    return 'http://192.168.68.159:8000';
  }
}
