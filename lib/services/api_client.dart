import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class ApiClient {
  static final ApiClient _instance = ApiClient._internal();
  factory ApiClient() => _instance;

  late Dio _dio;

  // Production URL (Railway)
  static const String _productionUrl =
      "https://pregrader-production.up.railway.app";

  // Local development URLs
  static const String _localIosUrl = "http://192.168.68.103:8000";
  static const String _androidEmulatorUrl = "http://10.0.2.2:8000";

  // API version - use v2 for hybrid detection
  static const String _apiVersion = "v2";

  ApiClient._internal() {
    String baseUrl;

    if (kReleaseMode) {
      // In release mode, always use production Railway URL
      baseUrl = _productionUrl;
    } else if (!kIsWeb && Platform.isAndroid) {
      baseUrl = _androidEmulatorUrl;
    } else {
      baseUrl = _localIosUrl;
    }

    _dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 60), // Increased for AI detection
      ),
    );

    if (kDebugMode) {
      _dio.interceptors.add(
        LogInterceptor(requestBody: true, responseBody: true),
      );
    }
  }

  /// Starts a new grading session
  Future<String> startGradingSession() async {
    try {
      Response response = await _dio.post("/api/$_apiVersion/grading/start");

      if (response.statusCode == 200) {
        return response.data["session_id"];
      } else {
        throw Exception("Failed to start session: ${response.statusMessage}");
      }
    } catch (e) {
      throw Exception("Session Error: $e");
    }
  }

  /// Uploads front image with hybrid detection
  Future<Map<String, dynamic>> uploadFrontImage({
    required String sessionId,
    required File frontImage,
  }) async {
    try {
      FormData formData = FormData.fromMap({
        "file": await MultipartFile.fromFile(
          frontImage.path,
          filename: "front.jpg",
        ),
      });

      Response response = await _dio.post(
        "/api/$_apiVersion/grading/$sessionId/upload-front",
        data: formData,
      );

      if (response.statusCode == 200) {
        return response.data;
      } else {
        throw Exception("Failed to upload front: ${response.statusMessage}");
      }
    } catch (e) {
      throw Exception("Upload Front Error: $e");
    }
  }

  /// Uploads back image with hybrid detection
  Future<Map<String, dynamic>> uploadBackImage({
    required String sessionId,
    required File backImage,
  }) async {
    try {
      FormData formData = FormData.fromMap({
        "file": await MultipartFile.fromFile(
          backImage.path,
          filename: "back.jpg",
        ),
      });

      Response response = await _dio.post(
        "/api/$_apiVersion/grading/$sessionId/upload-back",
        data: formData,
      );

      if (response.statusCode == 200) {
        return response.data;
      } else {
        throw Exception("Failed to upload back: ${response.statusMessage}");
      }
    } catch (e) {
      throw Exception("Upload Back Error: $e");
    }
  }

  /// Gets the final grading result
  Future<Map<String, dynamic>> getGradingResult(String sessionId) async {
    try {
      Response response = await _dio.get(
        "/api/$_apiVersion/grading/$sessionId/result",
      );

      if (response.statusCode == 200) {
        return response.data;
      } else {
        throw Exception("Failed to get result: ${response.statusMessage}");
      }
    } catch (e) {
      throw Exception("Result Error: $e");
    }
  }

  /// Gets debug visualization URL (optional)
  String getDebugVisualizationUrl(String sessionId) {
    String baseUrl;
    if (kReleaseMode) {
      baseUrl = _productionUrl;
    } else if (!kIsWeb && Platform.isAndroid) {
      baseUrl = _androidEmulatorUrl;
    } else {
      baseUrl = _localIosUrl;
    }
    return "$baseUrl/api/$_apiVersion/debug/$sessionId/visualization";
  }

  /// Legacy method for backward compatibility
  @Deprecated('Use startGradingSession, uploadFrontImage, uploadBackImage instead')
  Future<String> uploadImages({
    required File frontImage,
    File? backImage,
  }) async {
    try {
      // Start session
      String sessionId = await startGradingSession();

      // Upload front
      await uploadFrontImage(sessionId: sessionId, frontImage: frontImage);

      // Upload back if provided
      if (backImage != null) {
        await uploadBackImage(sessionId: sessionId, backImage: backImage);
      }

      return sessionId;
    } catch (e) {
      throw Exception("Upload Error: $e");
    }
  }

  /// Legacy method for backward compatibility
  @Deprecated('Use getGradingResult instead')
  Future<Map<String, dynamic>> getGrade(String sessionId) async {
    return await getGradingResult(sessionId);
  }
}
