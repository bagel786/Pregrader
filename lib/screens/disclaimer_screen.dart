import 'package:flutter/material.dart';

class DisclaimerScreen extends StatelessWidget {
  const DisclaimerScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Disclaimer'),
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.info_outline,
              size: 64,
              color: Colors.purple,
            ),
            const SizedBox(height: 24),
            Text(
              'Important Information',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 16),
            _buildSection(
              context,
              title: 'Estimation Only',
              content:
                  'Pokemon Pregrader is an estimation tool designed to provide a preliminary assessment of your card\'s condition. Our grading system uses image analysis to evaluate various factors, but it is NOT a substitute for professional grading services.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Accuracy Limitations',
              content:
                  'While we strive for accuracy, our model will not be 100% accurate. Factors such as lighting conditions, camera quality, image angles, and subtle card defects may affect the assessment. The actual grade from professional grading services may differ from our estimate.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Possible Underestimates',
              content:
                  'Our system is designed to be conservative in its assessments. This means we may underestimate the condition of your card to avoid overvaluing it. We believe it\'s better to be pleasantly surprised by a higher professional grade than disappointed by a lower one.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Not Professional Grading',
              content:
                  'This app does not replace professional grading services like PSA, BGS, or CGC. For official grading and authentication, please submit your cards to a recognized professional grading company.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Use at Your Own Risk',
              content:
                  'By using this app, you acknowledge that any decisions made based on our estimates are your own responsibility. We are not liable for any financial decisions or outcomes resulting from the use of this tool.',
            ),
            const SizedBox(height: 32),
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.purple.withOpacity(0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.purple.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.lightbulb_outline, color: Colors.purple),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'For best results, take photos in good lighting with the card centered in the frame.',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _buildSection(
    BuildContext context, {
    required String title,
    required String content,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.purple,
              ),
        ),
        const SizedBox(height: 8),
        Text(
          content,
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                height: 1.5,
              ),
        ),
      ],
    );
  }
}
