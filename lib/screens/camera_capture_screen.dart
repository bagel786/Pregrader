import 'dart:io';
import 'dart:math' as math;

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:image/image.dart' as img;
import '../services/camera_service.dart';
import '../services/card_detector_service.dart';
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

  // Detected card rect (normalized 0–1), null = no detection
  Rect? _detectedCard;
  // Smoothing buffer for detected rects (last N frames)
  final List<Rect> _rectHistory = [];
  static const int _smoothingFrames = 5;
  // Track consecutive misses to avoid instant flicker
  int _missCount = 0;
  static const int _missThreshold = 3;

  bool _isDetecting = false;

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
    if (ctrl.value.isStreamingImages) return;
    try {
      ctrl.startImageStream(_onCameraImage);
    } catch (_) {}
  }

  void _onCameraImage(CameraImage camImage) {
    // Throttle to ~2fps
    if (_frameSkip++ % 15 != 0) return;
    if (_isDetecting) return;
    _isDetecting = true;

    _detectCardVision(camImage).then((detected) {
      if (!mounted) return;
      _isDetecting = false;

      CameraReadiness newReadiness;
      String newHint;
      Rect? newDetected;

      if (detected != null) {
        _missCount = 0;
        _rectHistory.add(detected);
        if (_rectHistory.length > _smoothingFrames) {
          _rectHistory.removeAt(0);
        }
        newDetected = _weightedAverageRects(_rectHistory);

        final area = newDetected.width * newDetected.height;
        if (area > 0.15) {
          newReadiness = CameraReadiness.ready;
          newHint = 'Card detected — tap to capture';
        } else {
          newReadiness = CameraReadiness.nearReady;
          newHint = 'Move closer to the card';
        }
      } else {
        _missCount++;
        if (_missCount >= _missThreshold) {
          // Only clear after several consecutive misses to avoid flicker
          _rectHistory.clear();
          newDetected = null;
          newReadiness = CameraReadiness.notReady;
          newHint = 'Align card within the frame';
        } else {
          // Keep showing last known rect briefly
          newDetected = _detectedCard;
          newReadiness = _readiness;
          newHint = _hint;
        }
      }

      if (newReadiness != _readiness ||
          newHint != _hint ||
          newDetected != _detectedCard) {
        setState(() {
          _readiness = newReadiness;
          _hint = newHint;
          _detectedCard = newDetected;
        });
      }
    });
  }

  /// Pass raw BGRA bytes directly to native Vision via MethodChannel.
  /// No JPEG encoding, no file I/O, no pixel-by-pixel copy in Dart.
  Future<Rect?> _detectCardVision(CameraImage camImage) async {
    try {
      if (camImage.planes.isEmpty) return null;
      final plane = camImage.planes[0];

      final result = await CardDetectorService.detectRectangleFromBuffer(
        plane.bytes,
        camImage.width,
        camImage.height,
        plane.bytesPerRow,
      );
      if (result == null) return null;
      return result.boundingBox;
    } catch (_) {
      return null;
    }
  }

  /// Weighted average: recent frames get more weight for responsiveness.
  Rect _weightedAverageRects(List<Rect> rects) {
    if (rects.length == 1) return rects.first;
    double l = 0, t = 0, r = 0, b = 0, totalWeight = 0;
    for (int i = 0; i < rects.length; i++) {
      final weight = (i + 1).toDouble(); // newer frames get higher weight
      l += rects[i].left * weight;
      t += rects[i].top * weight;
      r += rects[i].right * weight;
      b += rects[i].bottom * weight;
      totalWeight += weight;
    }
    return Rect.fromLTRB(l / totalWeight, t / totalWeight, r / totalWeight, b / totalWeight);
  }

  Future<void> _takePicture() async {
    if (_isCapturing) return;

    setState(() {
      _isCapturing = true;
    });

    try {
      final ctrl = _cameraService.controller;
      if (ctrl != null && ctrl.value.isStreamingImages) {
        await ctrl.stopImageStream();
      }

      final XFile image = await _cameraService.takePicture();

      final XFile? croppedImage = await _cropImageToFrame(image);

      if (croppedImage == null) {
        throw Exception('Failed to crop image');
      }

      final validation = await ImageValidator.validateImage(croppedImage);
      final bool isValid = validation['isValid'] ?? false;
      final bool hasWarnings = validation['hasWarnings'] ?? false;

      if (!mounted) return;

      if (!isValid) {
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
        _startImageStream();
      }
    }
  }

  /// Crop the captured image to the card region.
  /// Saves the EXIF-baked image to a temp file, then runs Vision on that file
  /// so both Dart and Vision operate on identical pixel data.
  Future<XFile?> _cropImageToFrame(XFile imageFile) async {
    final screenSize = MediaQuery.of(context).size;
    final screenWidth = screenSize.width;
    final screenHeight = screenSize.height;

    try {
      final bytes = await File(imageFile.path).readAsBytes();
      var decoded = img.decodeImage(bytes);
      if (decoded == null) return null;
      // Apply EXIF rotation so width/height match portrait orientation
      final image = img.bakeOrientation(decoded);

      final int imageWidth = image.width;
      final int imageHeight = image.height;

      // Save the baked (rotated) image to a temp file for Vision.
      // This eliminates all EXIF ambiguity — Vision sees exactly what we see.
      final bakedPath = imageFile.path.replaceAll('.jpg', '_baked.jpg');
      await File(bakedPath).writeAsBytes(img.encodeJpg(image, quality: 95));

      // Run Vision on the baked image
      Rect? cardRect;
      final visionResult = await CardDetectorService.detectRectangle(bakedPath);
      if (visionResult != null && visionResult.confidence > 0.3) {
        cardRect = visionResult.boundingBox;
      }

      // Fallback: use last live-stream detected rect (Vision coords in portrait space)
      // These are relative to the camera frame, which has the same portrait orientation
      // but may differ in field of view — still a reasonable approximation.
      final bool usesCoverMapping = cardRect == null;
      if (cardRect == null && _detectedCard != null) {
        cardRect = _detectedCard;
      }

      // Fallback: static guide rect
      if (cardRect == null) {
        final guideRect = staticGuideRect(Size(screenWidth, screenHeight));
        cardRect = Rect.fromLTRB(
          guideRect.left / screenWidth,
          guideRect.top / screenHeight,
          guideRect.right / screenWidth,
          guideRect.bottom / screenHeight,
        );
      }

      int cropX, cropY, cropW, cropH;

      if (!usesCoverMapping) {
        // Vision rect is relative to the baked image — map directly
        cropX = (cardRect.left * imageWidth).round();
        cropY = (cardRect.top * imageHeight).round();
        cropW = (cardRect.width * imageWidth).round();
        cropH = (cardRect.height * imageHeight).round();
      } else {
        // Live/guide rect is relative to the screen — account for cover-mode offset
        final ctrl = _cameraService.controller;
        double previewW = imageWidth.toDouble();
        double previewH = imageHeight.toDouble();
        if (ctrl != null && ctrl.value.isInitialized) {
          previewW = ctrl.value.previewSize!.height; // swapped for portrait
          previewH = ctrl.value.previewSize!.width;
        }

        final previewAspect = previewW / previewH;
        final screenAspect = screenWidth / screenHeight;

        double offsetX = 0, offsetY = 0;
        if (previewAspect < screenAspect) {
          final visibleHeight = imageWidth / screenAspect;
          offsetY = (imageHeight - visibleHeight) / 2;
        } else {
          final visibleWidth = imageHeight * screenAspect;
          offsetX = (imageWidth - visibleWidth) / 2;
        }

        final visibleW = imageWidth - 2 * offsetX;
        final visibleH = imageHeight - 2 * offsetY;

        cropX = (offsetX + cardRect.left * visibleW).round();
        cropY = (offsetY + cardRect.top * visibleH).round();
        cropW = (cardRect.width * visibleW).round();
        cropH = (cardRect.height * visibleH).round();
      }

      // Add 2% padding
      final padX = (cropW * 0.02).round();
      final padY = (cropH * 0.02).round();

      final finalX = (cropX - padX).clamp(0, imageWidth - 1);
      final finalY = (cropY - padY).clamp(0, imageHeight - 1);
      final finalW = (cropW + padX * 2).clamp(1, imageWidth - finalX);
      final finalH = (cropH + padY * 2).clamp(1, imageHeight - finalY);

      final croppedImage = img.copyCrop(
        image,
        x: finalX,
        y: finalY,
        width: finalW,
        height: finalH,
      );

      final croppedPath = imageFile.path.replaceAll('.jpg', '_cropped.jpg');
      final croppedFile = File(croppedPath);
      await croppedFile.writeAsBytes(img.encodeJpg(croppedImage, quality: 95));

      // Clean up temp baked file
      try { await File(bakedPath).delete(); } catch (_) {}

      return XFile(croppedPath);
    } catch (e) {
      if (!mounted) return imageFile;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not crop image, using original: $e')),
      );
      return imageFile;
    }
  }

  @override
  void dispose() {
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
          // Camera Preview — cover mode (fills entire screen, no black bars)
          LayoutBuilder(
            builder: (context, constraints) {
              final ctrl = _cameraService.controller!;
              final previewSize = ctrl.value.previewSize!;
              final previewW = previewSize.height;
              final previewH = previewSize.width;
              final screenW = constraints.maxWidth;
              final screenH = constraints.maxHeight;

              final scale = math.max(
                screenW / previewW,
                screenH / previewH,
              );

              return ClipRect(
                child: OverflowBox(
                  maxWidth: double.infinity,
                  maxHeight: double.infinity,
                  child: SizedBox(
                    width: previewW * scale,
                    height: previewH * scale,
                    child: CameraPreview(ctrl),
                  ),
                ),
              );
            },
          ),

          // Overlay with live readiness colour, hint, and detected card
          CameraOverlay(
            readiness: _readiness,
            hint: _hint,
            detectedCard: _detectedCard,
          ),

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
