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
    // Return early only if the controller is both non-null AND properly initialized
    if (_controller != null && _controller!.value.isInitialized) return;

    // Dispose any stale controller before creating a new one
    if (_controller != null) {
      await _safeDispose(_controller!);
      _controller = null;
    }

    _cameras ??= await availableCameras();
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
      ResolutionPreset.veryHigh,
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
    final ctrl = _controller;
    _controller = null;
    if (ctrl != null) {
      await _safeDispose(ctrl);
    }
  }

  static Future<void> _safeDispose(CameraController ctrl) async {
    try {
      if (ctrl.value.isStreamingImages) {
        await ctrl.stopImageStream();
      }
    } catch (_) {}
    try {
      await ctrl.dispose();
    } catch (_) {}
  }
}
