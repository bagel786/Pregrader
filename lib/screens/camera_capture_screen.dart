import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
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

      // Basic Validation
      final validation = await ImageValidator.validateImage(image);

      if (!mounted) return;

      if (validation['isValid'] == true) {
        if (mounted) {
          if (widget.isReturningResult) {
            Navigator.of(context).pop(image);
          } else {
            Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => ReviewScreen(frontImage: image),
              ),
            );
          }
        }
      } else {
        if (!mounted) return;
        final issues = (validation['issues'] as List).join("\n");

        final shouldProceed = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text("Capture Issue"),
            content: Text("$issues\n\nDo you want to use this image anyway?"),
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
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Card Captured (Forced)!')),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Capture failed: $e')));
      }
    } finally {
      if (mounted) {
        setState(() {
          _isCapturing = false;
        });
      }
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
          // Camera Preview - Centered (Undistorted, potentially letterboxed)
          Center(child: CameraPreview(_cameraService.controller!)),

          // Overlay
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
                  backgroundColor: _isCapturing ? Colors.grey : Colors.white,
                  child: _isCapturing
                      ? const CircularProgressIndicator()
                      : const Icon(Icons.camera_alt, color: Colors.black),
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
