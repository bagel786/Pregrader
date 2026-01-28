import 'dart:io';
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

  @override
  void initState() {
    super.initState();
    _initializeCamera();
  }

  Future<void> _initializeCamera() async {
    try {
      await _cameraService.initialize();
      if (mounted) {
        setState(() {
          _isInitialized = true;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _errorMessage = 'Failed to initialize camera: $e';
        });
      }
    }
  }

  Future<void> _takePicture() async {
    if (_isCapturing) return;

    setState(() {
      _isCapturing = true;
    });

    try {
      final XFile image = await _cameraService.takePicture();

      // Crop the image to the frame area
      final XFile? croppedImage = await _cropImageToFrame(image);
      
      if (croppedImage == null) {
        throw Exception('Failed to crop image');
      }

      // Validate the captured image
      final validation = await ImageValidator.validateImage(croppedImage);
      final bool cardDetected = validation['cardDetected'] ?? false;

      if (!mounted) return;

      if (validation['isValid'] == true) {
        // Image is valid, proceed
        if (mounted) {
          if (widget.isReturningResult) {
            Navigator.of(context).pop(croppedImage);
          } else {
            Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => ReviewScreen(frontImage: croppedImage),
              ),
            );
          }
        }
      } else {
        // Show issues to user
        if (!mounted) return;
        final issues = (validation['issues'] as List).join("\n");

        final shouldProceed = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: Row(
              children: [
                Icon(
                  cardDetected ? Icons.warning : Icons.error,
                  color: cardDetected ? Colors.orange : Colors.red,
                ),
                const SizedBox(width: 8),
                const Text("Image Quality Issue"),
              ],
            ),
            content: Text(
              "$issues\n\nFor best results, we recommend retaking the photo. Would you like to proceed anyway?",
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

        if (shouldProceed == true) {
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
        }
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
      }
    }
  }

  Future<XFile?> _cropImageToFrame(XFile imageFile) async {
    try {
      final bytes = await File(imageFile.path).readAsBytes();
      final image = img.decodeImage(bytes);

      if (image == null) return null;

      // Calculate the frame dimensions (same as overlay)
      // Standard card aspect ratio: 2.5/3.5 = ~0.714
      // Frame is 85% of screen width
      final screenWidth = MediaQuery.of(context).size.width;
      final screenHeight = MediaQuery.of(context).size.height;
      
      // Get the actual image dimensions
      final imageWidth = image.width;
      final imageHeight = image.height;
      
      // Calculate the frame size relative to the image
      // The camera preview might be scaled, so we need to account for that
      final previewAspectRatio = imageWidth / imageHeight;
      final screenAspectRatio = screenWidth / screenHeight;
      
      double frameWidthInImage;
      double frameHeightInImage;
      double offsetX;
      double offsetY;
      
      if (previewAspectRatio > screenAspectRatio) {
        // Image is wider than screen (letterboxed horizontally)
        final visibleImageWidth = imageHeight * screenAspectRatio;
        offsetX = (imageWidth - visibleImageWidth) / 2;
        offsetY = 0;
        
        frameWidthInImage = visibleImageWidth * 0.85;
        frameHeightInImage = frameWidthInImage / 0.714;
        
        offsetX += (visibleImageWidth - frameWidthInImage) / 2;
        offsetY = (imageHeight - frameHeightInImage) / 2;
      } else {
        // Image is taller than screen (letterboxed vertically)
        final visibleImageHeight = imageWidth / screenAspectRatio;
        offsetX = 0;
        offsetY = (imageHeight - visibleImageHeight) / 2;
        
        frameWidthInImage = imageWidth * 0.85;
        frameHeightInImage = frameWidthInImage / 0.714;
        
        offsetX = (imageWidth - frameWidthInImage) / 2;
        offsetY += (visibleImageHeight - frameHeightInImage) / 2;
      }

      // Crop the image
      final croppedImage = img.copyCrop(
        image,
        x: offsetX.round(),
        y: offsetY.round(),
        width: frameWidthInImage.round(),
        height: frameHeightInImage.round(),
      );

      // Save the cropped image
      final croppedPath = imageFile.path.replaceAll('.jpg', '_cropped.jpg');
      final croppedFile = File(croppedPath);
      await croppedFile.writeAsBytes(img.encodeJpg(croppedImage, quality: 95));

      return XFile(croppedPath);
    } catch (e) {
      print('Error cropping image: $e');
      return imageFile; // Return original if cropping fails
    }
  }

  @override
  void dispose() {
    _cameraService.dispose();
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

          // Overlay (no real-time detection, just visual guide)
          const CameraOverlay(),

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
