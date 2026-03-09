import 'package:flutter/material.dart';

class PrivacyPolicyScreen extends StatelessWidget {
  const PrivacyPolicyScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Privacy Policy'),
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.privacy_tip_outlined,
              size: 64,
              color: Colors.purple,
            ),
            const SizedBox(height: 24),
            Text(
              'Privacy Policy',
              style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
            ),
            const SizedBox(height: 8),
            Text(
              'Last updated: March 2026',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Colors.grey,
                  ),
            ),
            const SizedBox(height: 16),
            _buildSection(
              context,
              title: 'Data Collection',
              content:
                  'Pokemon Pregrader does not require an account and does not collect any personal information. We do not ask for your name, email, location, or any other identifying data.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Image Handling',
              content:
                  'When you scan a card, your photo is uploaded to our server for analysis. Images are stored temporarily for up to 15 minutes to complete the grading process, then automatically and permanently deleted. Images are never saved to a database, shared with other users, or used for any purpose other than generating your grade.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Third-Party Services',
              content:
                  'In some cases, if our primary image analysis cannot confidently detect your card, your image may be sent to Anthropic\'s Claude Vision API as a fallback for improved detection. Anthropic\'s use of this data is governed by their own privacy policy. We also query the Pokemon TCG API (pokemontcg.io) for card metadata — no user data or images are sent to this service.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Logging',
              content:
                  'Our server maintains technical diagnostic logs (processing times, error messages, detection methods used). These logs do not contain any personally identifiable information such as IP addresses, device identifiers, or user data.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Analytics & Tracking',
              content:
                  'Pokemon Pregrader does not use any analytics services, advertising frameworks, cookies, or user tracking of any kind. We do not track you across apps or websites.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Data Retention',
              content:
                  'All session data is held in memory only and is not persisted to any database. Sessions and associated images are automatically deleted after 15 minutes. When the server restarts, all session data is cleared.',
            ),
            const SizedBox(height: 20),
            _buildSection(
              context,
              title: 'Your Rights',
              content:
                  'Since we do not collect or store personal data, there is no personal data to access, correct, or delete. If you have questions or concerns about your privacy, please contact us using the support information in the App Store listing.',
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
