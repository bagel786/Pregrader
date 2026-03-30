import 'dart:io';

import 'package:cunning_document_scanner/cunning_document_scanner.dart';
import 'package:flutter/material.dart';
import '../core/utils/image_validator.dart';
import 'review_screen.dart';

class DocumentScanCaptureScreen extends StatefulWidget {
  final bool isReturningResult;

  const DocumentScanCaptureScreen(
      {super.key, this.isReturningResult = false});

  @override
  State<DocumentScanCaptureScreen> createState() =>
      _DocumentScanCaptureScreenState();
}

class _DocumentScanCaptureScreenState
    extends State<DocumentScanCaptureScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scan());
  }

  Future<void> _scan() async {
    if (!mounted) return;

    try {
      final List<String>? paths =
          await CunningDocumentScanner.getPictures(noOfPages: 1);

      if (!mounted) return;

      if (paths == null || paths.isEmpty) {
        // User cancelled the scanner
        Navigator.of(context).pop();
        return;
      }

      final file = File(paths.first);
      final validation = await ImageValidator.validateImage(file);
      final bool isValid = validation['isValid'] ?? false;
      final bool hasWarnings = validation['hasWarnings'] ?? false;

      if (!mounted) return;

      if (!isValid) {
        final issues = (validation['issues'] as List<dynamic>).join('\n');
        final shouldProceed = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Row(
              children: [
                Icon(Icons.error, color: Colors.red),
                SizedBox(width: 8),
                Text('Card Not Detected'),
              ],
            ),
            content: Text(
              '$issues\n\nFor accurate grading the card must fill the frame clearly. Would you like to proceed anyway?',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Retake'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Use Anyway'),
              ),
            ],
          ),
        );
        if (shouldProceed != true) {
          // Re-launch scanner for retake
          _scan();
          return;
        }
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
        Navigator.of(context).pop(file);
      } else {
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ReviewScreen(frontImage: file),
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString().toLowerCase();
      final isPermission =
          msg.contains('permission') || msg.contains('denied') || msg.contains('not granted');

      if (isPermission) {
        await showDialog<void>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('Camera Permission Required'),
            content: const Text(
              'Camera access was denied. Please enable it in Settings > Privacy & Security > Camera.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('OK'),
              ),
            ],
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Scan failed: $e')),
        );
      }

      if (mounted) Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const CircularProgressIndicator(color: Colors.white),
            const SizedBox(height: 16),
            const Text(
              'Opening scanner...',
              style: TextStyle(color: Colors.white70),
            ),
          ],
        ),
      ),
    );
  }
}
