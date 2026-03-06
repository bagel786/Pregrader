import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
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
  static const int _smoothingFrames = 3;

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

  void _onCameraImage(CameraImage image) {
    // Throttle to ~2fps
    if (_frameSkip++ % 15 != 0) return;

    final detected = _detectCardEdges(image);

    CameraReadiness newReadiness;
    String newHint;
    Rect? newDetected;

    if (detected != null) {
      _rectHistory.add(detected);
      if (_rectHistory.length > _smoothingFrames) {
        _rectHistory.removeAt(0);
      }
      newDetected = _averageRects(_rectHistory);

      final area = newDetected.width * newDetected.height;
      if (area > 0.15) {
        newReadiness = CameraReadiness.ready;
        newHint = 'Card detected — tap to capture';
      } else {
        newReadiness = CameraReadiness.nearReady;
        newHint = 'Move closer to the card';
      }
    } else {
      _rectHistory.clear();
      newDetected = null;
      newReadiness = CameraReadiness.notReady;
      newHint = 'Align card within the frame';
    }

    if (mounted &&
        (newReadiness != _readiness ||
            newHint != _hint ||
            newDetected != _detectedCard)) {
      setState(() {
        _readiness = newReadiness;
        _hint = newHint;
        _detectedCard = newDetected;
      });
    }
  }

  /// Lightweight edge detection for live stream using gradient magnitude.
  /// Returns normalized rect (0–1) or null if no card found.
  Rect? _detectCardEdges(CameraImage image) {
    try {
      final int w = image.width;
      final int h = image.height;
      if (w == 0 || h == 0) return null;

      final ImageFormatGroup format = image.format.group;

      const int gridCols = 30;
      const int gridRows = 40;
      final int stepX = (w / gridCols).round().clamp(1, w);
      final int stepY = (h / gridRows).round().clamp(1, h);

      // Build brightness grid
      final grid = List.generate(gridRows, (_) => List.filled(gridCols, 0));

      if (format == ImageFormatGroup.yuv420) {
        final Uint8List yPlane = image.planes[0].bytes;
        final int rowStride = image.planes[0].bytesPerRow;
        for (int row = 0; row < gridRows; row++) {
          for (int col = 0; col < gridCols; col++) {
            final int py = (row * stepY).clamp(0, h - 1);
            final int px = (col * stepX).clamp(0, w - 1);
            final int idx = py * rowStride + px;
            if (idx < yPlane.length) {
              grid[row][col] = yPlane[idx];
            }
          }
        }
      } else if (format == ImageFormatGroup.bgra8888) {
        final Uint8List bytes = image.planes[0].bytes;
        final int rowStride = image.planes[0].bytesPerRow;
        for (int row = 0; row < gridRows; row++) {
          for (int col = 0; col < gridCols; col++) {
            final int py = (row * stepY).clamp(0, h - 1);
            final int px = (col * stepX).clamp(0, w - 1);
            final int offset = py * rowStride + px * 4;
            if (offset + 2 < bytes.length) {
              final int b = bytes[offset];
              final int g = bytes[offset + 1];
              final int r = bytes[offset + 2];
              grid[row][col] = (0.299 * r + 0.587 * g + 0.114 * b).round();
            }
          }
        }
      } else {
        return null;
      }

      // Compute gradient magnitude to find edges (not just brightness)
      final gradientGrid =
          List.generate(gridRows, (_) => List.filled(gridCols, 0));
      for (int row = 1; row < gridRows - 1; row++) {
        for (int col = 1; col < gridCols - 1; col++) {
          final gx = grid[row][col + 1] - grid[row][col - 1];
          final gy = grid[row + 1][col] - grid[row - 1][col];
          gradientGrid[row][col] = (gx * gx + gy * gy);
        }
      }

      // Find gradient threshold (strong edges)
      int maxGrad = 0;
      for (int row = 1; row < gridRows - 1; row++) {
        for (int col = 1; col < gridCols - 1; col++) {
          if (gradientGrid[row][col] > maxGrad) {
            maxGrad = gradientGrid[row][col];
          }
        }
      }
      if (maxGrad < 500) return null; // No significant edges

      final int gradThreshold = (maxGrad * 0.15).round();

      // Find bounding box of strong edge pixels
      int topRow = gridRows, bottomRow = 0;
      int leftCol = gridCols, rightCol = 0;

      for (int row = 1; row < gridRows - 1; row++) {
        for (int col = 1; col < gridCols - 1; col++) {
          if (gradientGrid[row][col] >= gradThreshold) {
            if (row < topRow) topRow = row;
            if (row > bottomRow) bottomRow = row;
            if (col < leftCol) leftCol = col;
            if (col > rightCol) rightCol = col;
          }
        }
      }

      final int rectW = rightCol - leftCol;
      final int rectH = bottomRow - topRow;
      if (rectW < 5 || rectH < 5) return null;
      if (rectW > gridCols * 0.95 && rectH > gridRows * 0.95) return null;

      final double normLeft = leftCol / gridCols;
      final double normTop = topRow / gridRows;
      final double normRight = (rightCol + 1) / gridCols;
      final double normBottom = (bottomRow + 1) / gridRows;

      // Validate aspect ratio is roughly card-shaped
      final double aspectRatio =
          (normRight - normLeft) / (normBottom - normTop);
      if (aspectRatio < 0.4 || aspectRatio > 1.2) return null;

      return Rect.fromLTRB(normLeft, normTop, normRight, normBottom);
    } catch (_) {
      return null;
    }
  }

  Rect _averageRects(List<Rect> rects) {
    if (rects.length == 1) return rects.first;
    double l = 0, t = 0, r = 0, b = 0;
    for (final rect in rects) {
      l += rect.left;
      t += rect.top;
      r += rect.right;
      b += rect.bottom;
    }
    final n = rects.length;
    return Rect.fromLTRB(l / n, t / n, r / n, b / n);
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
  /// Uses iOS Vision framework (VNDetectRectanglesRequest) for precise detection,
  /// falling back to the live-stream rect or static guide.
  Future<XFile?> _cropImageToFrame(XFile imageFile) async {
    final screenSize = MediaQuery.of(context).size;
    final screenWidth = screenSize.width;
    final screenHeight = screenSize.height;

    try {
      final bytes = await File(imageFile.path).readAsBytes();
      final image = img.decodeImage(bytes);
      if (image == null) return null;

      final int imageWidth = image.width;
      final int imageHeight = image.height;

      // Try native Vision rectangle detection (iOS only, returns null on Android)
      Rect? cardRect;
      final visionResult =
          await CardDetectorService.detectRectangle(imageFile.path);
      if (visionResult != null && visionResult.confidence > 0.5) {
        // Vision returns coords relative to the full captured image — use directly
        cardRect = visionResult.boundingBox;
      }

      // Fallback: use last live-stream detected rect
      // Note: live rect is relative to the screen/preview, needs cover-mode mapping
      final bool usesCoverMapping = cardRect == null;
      if (cardRect == null && _detectedCard != null) {
        cardRect = _detectedCard;
      }

      // Fallback: static guide rect mapped to normalized screen coords
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
        // Vision rect is relative to the full image — map directly
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
