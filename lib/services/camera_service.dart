import 'package:camera/camera.dart';

class CameraService {
  static final CameraService _instance = CameraService._internal();

  factory CameraService() {
    return _instance;
  }

  CameraService._internal();

  CameraController? _controller;
  List<CameraDescription>? _cameras;

  CameraController? get controller => _controller;

  Future<void> initialize() async {
    if (_controller != null) return;

    _cameras = await availableCameras();
    if (_cameras == null || _cameras!.isEmpty) {
      throw Exception('No cameras available');
    }

    // Select the first rear camera
    final rearCamera = _cameras!.firstWhere(
      (camera) => camera.lensDirection == CameraLensDirection.back,
      orElse: () => _cameras!.first,
    );

    _controller = CameraController(
      rearCamera,
      ResolutionPreset.high,
      enableAudio: false,
    );

    await _controller!.initialize();
  }

  Future<XFile> takePicture() async {
    if (_controller == null || !_controller!.value.isInitialized) {
      throw Exception('Camera not initialized');
    }

    if (_controller!.value.isTakingPicture) {
      throw Exception('Camera is already taking a picture');
    }

    try {
      return await _controller!.takePicture();
    } catch (e) {
      throw Exception('Failed to take picture: $e');
    }
  }

  Future<void> dispose() async {
    await _controller?.dispose();
    _controller = null;
  }
}
