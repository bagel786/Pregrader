import 'dart:io';
import 'dart:typed_data';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:image/image.dart' as img;
import '../services/camera_service.dart';
import '../widgets/camera_overlay.dart';
import '../core/utils/image_validator.dart';
import 'review_screen.dart';

class CameraCaptureScreen extends StatefulWidget {
  final bool isReturningResult;

  const CameraCaptureScreen({super.key, this.isReturningResult = false});

  @override
  State<CameraCaptureScreen> createState() => _CameraCaptureScreenState();
}

class _CameraCaptureScreenState extends State<CameraCaptureScreen> {
  final CameraService _cameraService = CameraService();
  bool _isInitialized = false;
  bool _isCapturing = false;
  String? _errorMessage;

  // Live guidance state
  CameraReadiness _readiness = CameraReadiness.notReady;
  String _hint = 'Align card within the frame';
  int _frameSkip = 0;

  @override
  void initState() {
    super.initState();
    _initializeCamera();
  }

  Future<void> _initializeCamera() async {
    try {
      await _cameraService.initialize();
      if (!mounted) return;
      setState(() {
        _isInitialized = true;
      });
      // Defer stream start to next frame so camera is fully settled
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _startImageStream();
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = 'Failed to initialize camera: $e';
        });
      }
    }
  }

  void _startImageStream() {
    final ctrl = _cameraService.controller;
    if (ctrl == null || !ctrl.value.isInitialized) return;
    if (ctrl.value.isStreamingImages) return; // already streaming
    try {
      ctrl.startImageStream(_onCameraImage);
    } catch (_) {
      // Stream unavailable — live guidance disabled, app continues normally
    }
  }

  void _onCameraImage(CameraImage image) {
    // Throttle to ~2fps
    if (_frameSkip++ % 15 != 0) return;

    final samples = _sampleBrightness(image);
    if (samples.isEmpty) return;

    final double mean = samples.reduce((a, b) => a + b) / samples.length;
    final double variance = samples
            .map((s) => (s - mean) * (s - mean))
            .reduce((a, b) => a + b) /
        samples.length;

    CameraReadiness newReadiness;
    String newHint;

    if (variance > 800) {
      newReadiness = CameraReadiness.ready;
      newHint = 'Card detected — tap to capture';
    } else if (variance > 300) {
      newReadiness = CameraReadiness.nearReady;
      newHint = 'Move closer to the card';
    } else {
      newReadiness = CameraReadiness.notReady;
      newHint = 'Align card within the frame';
    }

    if (mounted && (newReadiness != _readiness || newHint != _hint)) {
      setState(() {
        _readiness = newReadiness;
        _hint = newHint;
      });
    }
  }

  /// Sample brightness values from a 4×4 grid in the center 40% of the frame.
  /// Handles both yuv420 (Android) and bgra8888 (iOS) formats.
  List<int> _sampleBrightness(CameraImage image) {
    try {
      final int w = image.width;
      final int h = image.height;

      final int startX = (w * 0.30).round();
      final int endX = (w * 0.70).round();
      final int startY = (h * 0.30).round();
      final int endY = (h * 0.70).round();

      final int stepX = ((endX - startX) / 3).round().clamp(1, w);
      final int stepY = ((endY - startY) / 3).round().clamp(1, h);

      final List<int> values = [];
      final ImageFormatGroup format = image.format.group;

      if (format == ImageFormatGroup.yuv420) {
        final Uint8List yPlane = image.planes[0].bytes;
        final int rowStride = image.planes[0].bytesPerRow;
        for (int y = startY; y <= endY; y += stepY) {
          for (int x = startX; x <= endX; x += stepX) {
            final int idx = y * rowStride + x;
            if (idx < yPlane.length) {
              values.add(yPlane[idx]);
            }
          }
        }
      } else if (format == ImageFormatGroup.bgra8888) {
        final Uint8List bytes = image.planes[0].bytes;
        final int rowStride = image.planes[0].bytesPerRow;
        for (int y = startY; y <= endY; y += stepY) {
          for (int x = startX; x <= endX; x += stepX) {
            final int offset = y * rowStride + x * 4;
            if (offset + 2 < bytes.length) {
              final int b = bytes[offset];
              final int g = bytes[offset + 1];
              final int r = bytes[offset + 2];
              values.add((0.299 * r + 0.587 * g + 0.114 * b).round());
            }
          }
        }
      }

      return values;
    } catch (_) {
      return [];
    }
  }

  Future<void> _takePicture() async {
    if (_isCapturing) return;

    setState(() {
      _isCapturing = true;
    });

    try {
      // Stop stream before capture to avoid conflict
      final ctrl = _cameraService.controller;
      if (ctrl != null && ctrl.value.isStreamingImages) {
        await ctrl.stopImageStream();
      }

      final XFile image = await _cameraService.takePicture();

      // Crop the image to the frame area
      final XFile? croppedImage = await _cropImageToFrame(image);

      if (croppedImage == null) {
        throw Exception('Failed to crop image');
      }

      // Validate the captured image
      final validation = await ImageValidator.validateImage(croppedImage);
      final bool isValid = validation['isValid'] ?? false;
      final bool hasWarnings = validation['hasWarnings'] ?? false;

      if (!mounted) return;

      if (!isValid) {
        // Hard failure — card not detected or resolution too low
        final issues = (validation['issues'] as List<dynamic>).join("\n");
        final shouldProceed = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Row(
              children: [
                Icon(Icons.error, color: Colors.red),
                SizedBox(width: 8),
                Text("Card Not Detected"),
              ],
            ),
            content: Text(
              "$issues\n\nFor accurate grading the card must fill the frame clearly. Would you like to proceed anyway?",
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text("Retake"),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text("Use Anyway"),
              ),
            ],
          ),
        );
        if (shouldProceed != true) return;
      } else if (hasWarnings) {
        // Soft warning — card detected but framing/resolution could be better
        final warnings = (validation['warnings'] as List<dynamic>).join(' ');
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Tip: $warnings'),
            duration: const Duration(seconds: 4),
            backgroundColor: Colors.orange[800],
          ),
        );
      }

      if (!mounted) return;
      if (widget.isReturningResult) {
        Navigator.of(context).pop(croppedImage);
      } else {
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ReviewScreen(frontImage: croppedImage),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Capture failed: $e')),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _isCapturing = false;
        });
        // Restart stream for continued guidance
        _startImageStream();
      }
    }
  }

  Future<XFile?> _cropImageToFrame(XFile imageFile) async {
    try {
      final bytes = await File(imageFile.path).readAsBytes();
      final image = img.decodeImage(bytes);

      if (image == null) return null;

      // Get screen dimensions
      final screenWidth = MediaQuery.of(context).size.width;
      final screenHeight = MediaQuery.of(context).size.height;

      // Calculate frame dimensions (same as overlay)
      final frameWidthOnScreen = screenWidth * 0.85;
      final frameHeightOnScreen = frameWidthOnScreen / 0.714;

      // Get image dimensions
      final imageWidth = image.width;
      final imageHeight = image.height;

      // Calculate scaling factors
      // The camera preview is scaled to fit the screen while maintaining aspect ratio
      final imageAspectRatio = imageWidth / imageHeight;
      final screenAspectRatio = screenWidth / screenHeight;

      double scaleX, scaleY;
      double offsetX = 0, offsetY = 0;

      if (imageAspectRatio > screenAspectRatio) {
        // Image is wider - it's scaled to fit height, with horizontal letterboxing
        scaleY = imageHeight / screenHeight;
        scaleX = scaleY;

        final scaledImageWidth = imageWidth / scaleX;
        offsetX = (scaledImageWidth - screenWidth) / 2 * scaleX;
      } else {
        // Image is taller - it's scaled to fit width, with vertical letterboxing
        scaleX = imageWidth / screenWidth;
        scaleY = scaleX;

        final scaledImageHeight = imageHeight / scaleY;
        offsetY = (scaledImageHeight - screenHeight) / 2 * scaleY;
      }

      // Calculate frame position in image coordinates
      final frameXOnScreen = (screenWidth - frameWidthOnScreen) / 2;
      final frameYOnScreen = (screenHeight - frameHeightOnScreen) / 2;

      final frameXInImage = (frameXOnScreen * scaleX + offsetX).round();
      final frameYInImage = (frameYOnScreen * scaleY + offsetY).round();
      final frameWidthInImage = (frameWidthOnScreen * scaleX).round();
      final frameHeightInImage = (frameHeightOnScreen * scaleY).round();

      // Ensure crop bounds are within image
      final cropX = frameXInImage.clamp(0, imageWidth - 1);
      final cropY = frameYInImage.clamp(0, imageHeight - 1);
      final cropWidth = (frameWidthInImage).clamp(1, imageWidth - cropX);
      final cropHeight = (frameHeightInImage).clamp(1, imageHeight - cropY);

      // Crop the image
      final croppedImage = img.copyCrop(
        image,
        x: cropX,
        y: cropY,
        width: cropWidth,
        height: cropHeight,
      );

      // Save the cropped image
      final croppedPath = imageFile.path.replaceAll('.jpg', '_cropped.jpg');
      final croppedFile = File(croppedPath);
      await croppedFile.writeAsBytes(img.encodeJpg(croppedImage, quality: 95));

      return XFile(croppedPath);
    } catch (e) {
      if (!mounted) return imageFile;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not crop image, using original: $e')),
      );
      return imageFile; // Return original if cropping fails
    }
  }

  @override
  void dispose() {
    // Defer disposal to next microtask so CameraPreview's ValueListenableBuilder
    // can remove its listener before stopImageStream fires notifyListeners.
    final svc = _cameraService;
    Future.microtask(() => svc.dispose());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_errorMessage != null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Camera Error')),
        body: Center(child: Text(_errorMessage!)),
      );
    }

    if (!_isInitialized) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          // Camera Preview - Centered
          Center(child: CameraPreview(_cameraService.controller!)),

          // Overlay with live readiness colour and hint
          CameraOverlay(readiness: _readiness, hint: _hint),

          // Controls
          Positioned(
            bottom: 40,
            left: 0,
            right: 0,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                FloatingActionButton(
                  onPressed: _isCapturing ? null : _takePicture,
                  backgroundColor: _isCapturing
                      ? Colors.grey
                      : Theme.of(context).colorScheme.primary,
                  child: _isCapturing
                      ? const CircularProgressIndicator(color: Colors.white)
                      : const Icon(Icons.camera_alt, color: Colors.white),
                ),
              ],
            ),
          ),

          // Back Button
          Positioned(
            top: 50,
            left: 16,
            child: IconButton(
              icon: const Icon(Icons.arrow_back, color: Colors.white),
              onPressed: () => Navigator.of(context).pop(),
            ),
          ),
        ],
      ),
    );
  }
}
