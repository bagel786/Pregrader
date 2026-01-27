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
        receiveTimeout: const Duration(seconds: 30),
      ),
    );

    if (kDebugMode) {
      _dio.interceptors.add(
        LogInterceptor(requestBody: true, responseBody: true),
      );
    }
  }

  /// Uploads card images and returns the session_id
  Future<String> uploadImages({
    required File frontImage,
    File? backImage,
  }) async {
    try {
      FormData formData = FormData.fromMap({
        "front_image": await MultipartFile.fromFile(frontImage.path),
      });

      if (backImage != null) {
        formData.files.add(
          MapEntry("back_image", await MultipartFile.fromFile(backImage.path)),
        );
      }

      Response response = await _dio.post("/analyze/upload", data: formData);

      if (response.statusCode == 200) {
        return response.data["session_id"];
      } else {
        throw Exception("Failed to upload: ${response.statusMessage}");
      }
    } catch (e) {
      throw Exception("Upload Error: $e");
    }
  }

  /// Retrieves the grading result for a session
  Future<Map<String, dynamic>> getGrade(String sessionId) async {
    try {
      // POST /grade?session_id=...
      Response response = await _dio.post(
        "/grade",
        queryParameters: {"session_id": sessionId},
      );

      if (response.statusCode == 200) {
        return response.data;
      } else {
        throw Exception("Failed to get grade: ${response.statusMessage}");
      }
    } catch (e) {
      throw Exception("Grading Error: $e");
    }
  }
}
