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

  // Progress tracking
  int _gradingStep = 0;    // 0 = idle
  String _stepLabel = '';
  double _stepProgress = 0.0;

  static const List<(String, double)> _steps = [
    ('Starting session...', 0.10),
    ('Uploading front image...', 0.35),
    ('Uploading back image...', 0.60),
    ('Analyzing card...', 0.85),
    ('Finalizing grade...', 0.95),
  ];

  void _setStep(int step) {
    if (!mounted) return;
    setState(() {
      _gradingStep = step;
      if (step > 0 && step <= _steps.length) {
        _stepLabel = _steps[step - 1].$1;
        _stepProgress = _steps[step - 1].$2;
      }
    });
  }

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
      _gradingStep = 0;
    });

    try {
      final client = ApiClient();

      // Step 1: Start session
      _setStep(1);
      final sessionId = await client.startGradingSession();

      // Step 2: Upload front image
      _setStep(2);
      await client.uploadFrontImage(
        sessionId: sessionId,
        frontImage: _frontFile,
      );

      // Step 3: Upload back if provided (skip step if no back)
      if (_backFile != null) {
        _setStep(3);
        await client.uploadBackImage(
          sessionId: sessionId,
          backImage: _backFile!,
        );
      }

      // Step 4: Analyze
      _setStep(4);
      final result = await client.getGradingResult(sessionId);

      // Step 5: Done
      _setStep(5);

      if (!mounted) return;

      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) =>
              ResultScreen(gradingResult: result, frontImage: _frontFile),
        ),
      );
    } catch (e) {
      if (mounted) {
        final errorMessage = e.toString();
        String displayError;

        if (errorMessage.contains("DioException") &&
            errorMessage.contains("SocketException")) {
          displayError =
              "Cannot connect to server. Please check your internet connection.";
        } else if (errorMessage.contains("timed out") ||
            errorMessage.contains("timeout")) {
          displayError =
              "Analysis timed out. Try again with better lighting or a closer photo.";
        } else if (errorMessage.contains("too large")) {
          displayError = "Image file is too large. Please try a smaller photo.";
        } else if (errorMessage.contains("404")) {
          displayError = "Session expired. Please try again.";
        } else if (errorMessage.contains("400")) {
          displayError =
              "Image quality issue detected. Retake with better lighting and ensure the card fills the frame.";
        } else {
          displayError = "Grading failed. Please try again.";
        }

        setState(() {
          _error = displayError;
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _isGrading = false;
          _gradingStep = 0;
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
                    _isGrading ? null : _captureBack,
                  ),
                  if (_isGrading) ...[
                    const SizedBox(height: 24),
                    _buildProgressPanel(),
                  ],
                  if (_error != null && !_isGrading)
                    Padding(
                      padding: const EdgeInsets.only(top: 20),
                      child: Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.red.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(
                              color: Colors.red.withValues(alpha: 0.4)),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.error_outline,
                                color: Colors.redAccent, size: 20),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _error!,
                                style: const TextStyle(color: Colors.white70),
                              ),
                            ),
                          ],
                        ),
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
                    disabledBackgroundColor: Colors.deepPurple.withValues(alpha: 0.4),
                  ),
                  child: _isGrading
                      ? const Text(
                          "Grading...",
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                            color: Colors.white54,
                          ),
                        )
                      : Text(
                          _error != null ? "RETRY" : "CONFIRM & GRADE",
                          style: const TextStyle(
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

  Widget _buildProgressPanel() {
    // Determine visible steps (skip step 3 if no back image)
    final List<String> visibleSteps = [
      'Create session',
      'Upload front',
      if (_backFile != null) 'Upload back',
      'Analyze card',
    ];
    final int totalVisible = visibleSteps.length;

    // Map _gradingStep (1-5) to visible step index
    int currentVisible = _gradingStep;
    if (_backFile == null && _gradingStep >= 3) {
      // Collapsed: step 3 (back) becomes 3 (analyze), step 4 is still analyze
      currentVisible = _gradingStep - 1;
    }

    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.deepPurple.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.deepPurple.withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.deepPurple,
                ),
              ),
              const SizedBox(width: 10),
              Text(
                _stepLabel,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: _stepProgress,
              backgroundColor: Colors.white12,
              valueColor:
                  const AlwaysStoppedAnimation<Color>(Colors.deepPurple),
              minHeight: 6,
            ),
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: List.generate(totalVisible, (i) {
              final done = currentVisible > i + 1;
              final active = currentVisible == i + 1;
              return _buildStepDot(
                  label: visibleSteps[i], done: done, active: active);
            }),
          ),
        ],
      ),
    );
  }

  Widget _buildStepDot(
      {required String label, required bool done, required bool active}) {
    final color = done
        ? Colors.green
        : active
            ? Colors.deepPurple
            : Colors.white24;
    return Column(
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(shape: BoxShape.circle, color: color),
        ),
        const SizedBox(height: 4),
        Text(
          label,
          style: TextStyle(color: color, fontSize: 9),
          textAlign: TextAlign.center,
        ),
      ],
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
                ? Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.add_a_photo,
                        color: onAdd != null ? Colors.white54 : Colors.white24,
                        size: 40,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        onAdd != null ? "Tap to add photo" : "No photo added",
                        style: TextStyle(
                          color: onAdd != null
                              ? Colors.white54
                              : Colors.white24,
                        ),
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
