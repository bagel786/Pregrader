import 'dart:io';
import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import '../services/api_client.dart';
import 'camera_capture_screen.dart';
import 'result_screen.dart';

class ReviewScreen extends StatefulWidget {
  final XFile frontImage;

  const ReviewScreen({super.key, required this.frontImage});

  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  late File _frontFile;
  File? _backFile;
  bool _isGrading = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _frontFile = File(widget.frontImage.path);
  }

  Future<void> _captureBack() async {
    final result = await Navigator.of(context).push<XFile>(
      MaterialPageRoute(
        builder: (_) => const CameraCaptureScreen(isReturningResult: true),
      ),
    );

    if (result != null) {
      setState(() {
        _backFile = File(result.path);
      });
    }
  }

  Future<void> _startGrading() async {
    setState(() {
      _isGrading = true;
      _error = null;
    });

    try {
      final client = ApiClient();

      // 1. Upload
      final sessionId = await client.uploadImages(
        frontImage: _frontFile,
        backImage: _backFile,
      );

      // 2. Poll/Get Grade
      final result = await client.getGrade(sessionId);

      if (!mounted) return;

      // 3. Navigate to Results
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) =>
              ResultScreen(gradingResult: result, frontImage: _frontFile),
        ),
      );
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e.toString();
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _isGrading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        title: const Text("Review Card"),
        backgroundColor: Colors.transparent,
      ),
      body: Column(
        children: [
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: [
                  _buildImageSection("Front", _frontFile, null),
                  const SizedBox(height: 20),
                  _buildImageSection(
                    "Back (Optional)",
                    _backFile,
                    _captureBack,
                  ),
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 20),
                      child: Text(
                        _error!,
                        style: const TextStyle(color: Colors.red),
                        textAlign: TextAlign.center,
                      ),
                    ),
                ],
              ),
            ),
          ),

          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: _isGrading ? null : _startGrading,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.deepPurple,
                    foregroundColor: Colors.white,
                  ),
                  child: _isGrading
                      ? const CircularProgressIndicator(color: Colors.white)
                      : const Text(
                          "CONFIRM & GRADE",
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildImageSection(String title, File? file, VoidCallback? onAdd) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(color: Colors.white70, fontSize: 16),
        ),
        const SizedBox(height: 8),
        GestureDetector(
          onTap: onAdd,
          child: Container(
            height: 250,
            width: double.infinity,
            decoration: BoxDecoration(
              color: Colors.grey[900],
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.white24),
              image: file != null
                  ? DecorationImage(image: FileImage(file), fit: BoxFit.contain)
                  : null,
            ),
            child: file == null
                ? const Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.add_a_photo, color: Colors.white54, size: 40),
                      SizedBox(height: 8),
                      Text(
                        "Tap to add photo",
                        style: TextStyle(color: Colors.white54),
                      ),
                    ],
                  )
                : null,
          ),
        ),
      ],
    );
  }
}
