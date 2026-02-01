import 'dart:io';
import 'package:flutter/material.dart';

class ResultScreen extends StatelessWidget {
  final Map<String, dynamic> gradingResult;
  final File frontImage;

  const ResultScreen({
    super.key,
    required this.gradingResult,
    required this.frontImage,
  });

  @override
  Widget build(BuildContext context) {
    final grading = gradingResult['grading'] ?? {};
    final finalScore = grading['final_score'] ?? 0.0;
    final psaEstimate = grading['psa_estimate'] ?? "?";

    // Fix: Handle confidence as Map (new format) or String (legacy)
    final confidenceData = grading['confidence'];
    String confidenceLevel = "Unknown";
    if (confidenceData is Map) {
      confidenceLevel = confidenceData['level']?.toString() ?? "Unknown";
    } else if (confidenceData is String) {
      confidenceLevel = confidenceData;
    }

    final subScores = grading['sub_scores'] as Map<String, dynamic>? ?? {};
    final explanations = grading['explanations'] as List<dynamic>? ?? [];

    return Scaffold(
      backgroundColor: Colors.black, // Premium Dark Mode
      appBar: AppBar(
        title: const Text("Grading Result"),
        backgroundColor: Colors.transparent,
        automaticallyImplyLeading: false,
        actions: [
          IconButton(
            icon: const Icon(Icons.close),
            onPressed: () =>
                Navigator.of(context).popUntil((route) => route.isFirst),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            // Disclaimer Notice
            Container(
              padding: const EdgeInsets.all(12),
              margin: const EdgeInsets.only(bottom: 20),
              decoration: BoxDecoration(
                color: Colors.purple.withOpacity(0.15),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.purple.withOpacity(0.4)),
              ),
              child: Column(
                children: [
                  Row(
                    children: [
                      const Icon(
                        Icons.info_outline,
                        color: Colors.purple,
                        size: 20,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'This is an estimate only. Results may vary from professional grading.',
                          style: TextStyle(
                            color: Colors.white.withOpacity(0.9),
                            fontSize: 13,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () {
                        Navigator.pushNamed(context, '/disclaimer');
                      },
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        minimumSize: const Size(0, 0),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      ),
                      child: const Text(
                        'Read Full Disclaimer',
                        style: TextStyle(
                          color: Colors.purple,
                          fontSize: 12,
                          decoration: TextDecoration.underline,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),

            // 1. Grade Badge
            Container(
              width: 150,
              height: 150,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: _getGradeColor(finalScore), width: 4),
                boxShadow: [
                  BoxShadow(
                    color: _getGradeColor(finalScore).withOpacity(0.5),
                    blurRadius: 20,
                    spreadRadius: 5,
                  ),
                ],
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    psaEstimate,
                    style: const TextStyle(
                      fontSize: 48,
                      fontWeight: FontWeight.bold,
                      color: Colors.white,
                    ),
                  ),
                  const Text(
                    "ESTIMATE",
                    style: TextStyle(fontSize: 12, color: Colors.white70),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            Text(
              "Raw Score: $finalScore / 10",
              style: const TextStyle(color: Colors.white54),
            ),
            const SizedBox(height: 5),
            _buildConfidenceChip(confidenceLevel),

            const SizedBox(height: 30),

            // 2. Sub-Scores Grid
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 2.5,
              crossAxisSpacing: 10,
              mainAxisSpacing: 10,
              children: [
                _buildSubResult("Centering", subScores['centering']),
                _buildSubResult("Corners", subScores['corners']),
                _buildSubResult("Edges", subScores['edges']),
                _buildSubResult("Surface", subScores['surface']),
              ],
            ),

            const SizedBox(height: 30),

            // 3. Explanations / Caps
            if (explanations.isNotEmpty) ...[
              const Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  "Analysis Details",
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              ...explanations.map((e) => _buildExplanationCard(e.toString())),
            ],

            const SizedBox(height: 40),

            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                onPressed: () =>
                    Navigator.of(context).popUntil((route) => route.isFirst),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Colors.white24),
                  padding: const EdgeInsets.symmetric(vertical: 16),
                ),
                child: const Text(
                  "Scan Another Card",
                  style: TextStyle(color: Colors.white),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Color _getGradeColor(dynamic score) {
    if (score is! num) return Colors.grey;
    if (score >= 9) return Colors.amber; // Gold
    if (score >= 8) return Colors.blue; // Silver/Blue
    if (score >= 7) return Colors.green;
    return Colors.red;
  }

  Widget _buildConfidenceChip(String confidence) {
    Color color = Colors.green;
    if (confidence == "Medium") color = Colors.orange;
    if (confidence == "Low") color = Colors.red;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color),
      ),
      child: Text(
        "Confidence: $confidence",
        style: TextStyle(color: color, fontSize: 12),
      ),
    );
  }

  Widget _buildSubResult(String label, dynamic value) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white10,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Colors.white70)),
          Text(
            value?.toString() ?? "-",
            style: const TextStyle(
              color: Colors.white,
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildExplanationCard(String text) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.red.withOpacity(0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.red.withOpacity(0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.warning_amber_rounded,
            color: Colors.redAccent,
            size: 20,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(text, style: const TextStyle(color: Colors.white70)),
          ),
        ],
      ),
    );
  }
}
