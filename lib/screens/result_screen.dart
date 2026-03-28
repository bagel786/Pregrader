import 'dart:convert';
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
    final grading = gradingResult['grading'] is Map
        ? Map<String, dynamic>.from(gradingResult['grading'] as Map)
        : <String, dynamic>{};

    // Safe extraction — null means data is genuinely missing, not grade 0
    final finalScore = (grading['final_score'] as num?)?.toDouble();
    final psaEstimate = grading['psa_estimate']?.toString() ?? "?";
    final gradeRange = grading['grade_range']?.toString();

    // Handle confidence as Map (new format) or String (legacy)
    final confidenceData = grading['confidence'];
    String confidenceLevel = "Unknown";
    if (confidenceData is Map) {
      confidenceLevel = confidenceData['level']?.toString() ?? "Unknown";
    } else if (confidenceData is String) {
      confidenceLevel = confidenceData;
    }

    // Grading status
    final gradingStatus = grading['grading_status']?.toString() ?? "success";
    final gradingStatusMessage = grading['grading_status_message']?.toString();

    // Safe type check — avoids runtime crash if API returns unexpected type
    final subScores = grading['sub_scores'] is Map
        ? Map<String, dynamic>.from(grading['sub_scores'] as Map)
        : <String, dynamic>{};
    final recommendations = grading['recommendations'] is List
        ? grading['recommendations'] as List<dynamic>
        : <dynamic>[];

    // Extract new fields for enhanced summary
    final annotatedImageB64 = gradingResult['annotated_front_image'] as String?;
    final details = (gradingResult['details'] as Map?)?.cast<String, dynamic>() ?? {};
    final frontCenteringDetails =
        (details['front_centering'] as Map?)?.cast<String, dynamic>() ??
            (details['centering'] as Map?)?.cast<String, dynamic>() ??
            <String, dynamic>{};
    final constraints =
        (grading['constraints_applied'] as Map?)?.cast<String, dynamic>() ?? {};
    final dimScores =
        (grading['dimension_scores'] as Map?)?.cast<String, dynamic>() ?? {};
    final defects = grading['defects'] is List ? grading['defects'] as List : [];

    // If finalScore is null, the API returned invalid data — show error state
    if (finalScore == null) {
      return _buildErrorScreen(context, "Could not read grading result",
          "The server returned an unexpected response. Please try again.");
    }

    // If grading was refused due to low confidence — show unable-to-grade state
    if (gradingStatus == "refused") {
      return _buildRefusedScreen(
          context, gradingStatusMessage, recommendations);
    }

    return Scaffold(
      backgroundColor: Colors.black,
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
                color: Colors.purple.withValues(alpha:0.15),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.purple.withValues(alpha:0.4)),
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
                          'Conservative estimate — actual grade is often equal to or better than shown.',
                          style: TextStyle(
                            color: Colors.white.withValues(alpha:0.9),
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

            // Low confidence warning banner
            if (gradingStatus == "low_confidence") ...[
              Container(
                padding: const EdgeInsets.all(12),
                margin: const EdgeInsets.only(bottom: 20),
                decoration: BoxDecoration(
                  color: Colors.orange.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                  border:
                      Border.all(color: Colors.orange.withValues(alpha: 0.6)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.warning_amber_rounded,
                        color: Colors.orange, size: 24),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        gradingStatusMessage ??
                            'Low confidence result — consider retaking photos.',
                        style: const TextStyle(
                            color: Colors.orange,
                            fontSize: 14,
                            fontWeight: FontWeight.w500),
                      ),
                    ),
                  ],
                ),
              ),
            ],

            // 1. Grade Badge
            Container(
              width: 150,
              height: 150,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: _getGradeColor(finalScore), width: 4),
                boxShadow: [
                  BoxShadow(
                    color: _getGradeColor(finalScore).withValues(alpha:0.5),
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
              "Raw Score: ${finalScore.toStringAsFixed(1)} / 10",
              style: const TextStyle(color: Colors.white54),
            ),
            if (gradeRange != null && gradeRange.contains('-')) ...[
              const SizedBox(height: 4),
              Text(
                "Near grade boundary — possible PSA $gradeRange",
                style: const TextStyle(color: Colors.orange, fontSize: 12),
              ),
            ],
            const SizedBox(height: 5),
            _buildConfidenceChip(confidenceLevel),

            const SizedBox(height: 30),

            // 2. Annotated card image
            if (annotatedImageB64 != null && annotatedImageB64.isNotEmpty)
              _buildAnnotatedImage(annotatedImageB64, frontImage),
            if (annotatedImageB64 != null && annotatedImageB64.isNotEmpty)
              const SizedBox(height: 24),

            // 3. Component tiles with color-coding and front/back split
            _buildComponentTiles(subScores, dimScores),

            const SizedBox(height: 20),

            // 4. Centering detail row
            _buildCenteringRow(frontCenteringDetails, constraints),

            const SizedBox(height: 20),

            // 5. Constraints panel (damage cap, floor/ceiling)
            _buildConstraintsPanel(constraints),
            if (_hasConstraints(constraints)) const SizedBox(height: 20),

            // 6. Defect list (grouped by location)
            if (defects.isNotEmpty) ...[
              _buildDefectList(defects),
              const SizedBox(height: 20),
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

  Scaffold _buildErrorScreen(
      BuildContext context, String title, String subtitle) {
    return Scaffold(
      backgroundColor: Colors.black,
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
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, color: Colors.redAccent, size: 64),
              const SizedBox(height: 16),
              Text(
                title,
                style: const TextStyle(color: Colors.white, fontSize: 18),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                subtitle,
                style: const TextStyle(color: Colors.white54, fontSize: 14),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 32),
              OutlinedButton(
                onPressed: () =>
                    Navigator.of(context).popUntil((route) => route.isFirst),
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Colors.white24),
                  padding:
                      const EdgeInsets.symmetric(vertical: 16, horizontal: 32),
                ),
                child: const Text("Try Again",
                    style: TextStyle(color: Colors.white)),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Scaffold _buildRefusedScreen(BuildContext context, String? message,
      List<dynamic> recommendations) {
    return Scaffold(
      backgroundColor: Colors.black,
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
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.warning_amber_rounded,
                  color: Colors.orange, size: 64),
              const SizedBox(height: 16),
              const Text(
                "Unable to Grade",
                style: TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.bold),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 12),
              Text(
                message ??
                    "Image quality too low for reliable analysis. Please retake photos with better lighting.",
                style: const TextStyle(color: Colors.white70, fontSize: 14),
                textAlign: TextAlign.center,
              ),
              if (recommendations.isNotEmpty) ...[
                const SizedBox(height: 24),
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    "Suggestions:",
                    style: TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.bold),
                  ),
                ),
                const SizedBox(height: 8),
                ...recommendations.map((r) => Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.lightbulb_outline,
                              color: Colors.orange, size: 18),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(r.toString(),
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 13)),
                          ),
                        ],
                      ),
                    )),
              ],
              const SizedBox(height: 32),
              ElevatedButton.icon(
                onPressed: () =>
                    Navigator.of(context).popUntil((route) => route.isFirst),
                icon: const Icon(Icons.camera_alt),
                label: const Text("Try Again"),
                style: ElevatedButton.styleFrom(
                  padding:
                      const EdgeInsets.symmetric(vertical: 16, horizontal: 32),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Color _getGradeColor(double score) {
    if (score >= 9) return Colors.amber;
    if (score >= 8) return Colors.blue;
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
        color: color.withValues(alpha:0.2),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color),
      ),
      child: Text(
        "Confidence: $confidence",
        style: TextStyle(color: color, fontSize: 12),
      ),
    );
  }

  // NEW WIDGETS FOR ENHANCED SUMMARY

  Widget _buildAnnotatedImage(String? b64, File fallback) {
    Widget imageWidget;

    if (b64 != null && b64.isNotEmpty) {
      try {
        final bytes = base64Decode(b64);
        imageWidget = Image.memory(
          bytes,
          fit: BoxFit.contain,
          errorBuilder: (_, _, _) => Image.file(fallback, fit: BoxFit.contain),
        );
      } catch (_) {
        imageWidget = Image.file(fallback, fit: BoxFit.contain);
      }
    } else {
      imageWidget = Image.file(fallback, fit: BoxFit.contain);
    }

    return Container(
      constraints: const BoxConstraints(maxHeight: 280),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white12),
      ),
      clipBehavior: Clip.antiAlias,
      child: imageWidget,
    );
  }

  Widget _buildComponentTiles(
      Map<String, dynamic> subScores, Map<String, dynamic> dimScores) {
    final cornersBlended =
        (dimScores['corners']?['blended'] as num?)?.toDouble();
    final cornersFront =
        (dimScores['corners']?['front_avg'] as num?)?.toDouble();
    final cornersBack =
        (dimScores['corners']?['back_avg'] as num?)?.toDouble();

    final edgesBlended = (dimScores['edges']?['blended'] as num?)?.toDouble();
    final edgesFront = (dimScores['edges']?['front_avg'] as num?)?.toDouble();
    final edgesBack = (dimScores['edges']?['back_avg'] as num?)?.toDouble();

    final surfaceBlended =
        (dimScores['surface']?['blended'] as num?)?.toDouble();
    final surfaceFront = (dimScores['surface']?['front'] as num?)?.toDouble();
    final surfaceBack = (dimScores['surface']?['back'] as num?)?.toDouble();

    final centeringScore = (subScores['centering'] as num?)?.toDouble();

    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _buildComponentTile(
                "Corners",
                cornersBlended,
                cornersFront,
                cornersBack,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _buildComponentTile(
                "Edges",
                edgesBlended,
                edgesFront,
                edgesBack,
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: _buildComponentTile(
                "Surface",
                surfaceBlended,
                surfaceFront,
                surfaceBack,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: _buildComponentTile("Centering", centeringScore, null, null),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildComponentTile(
    String label,
    double? score,
    double? front,
    double? back,
  ) {
    final color = _getScoreColor(score ?? 5.0);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(color: Colors.white54, fontSize: 12),
          ),
          const SizedBox(height: 4),
          Text(
            score != null ? score.toStringAsFixed(1) : "-",
            style: TextStyle(
              color: color,
              fontSize: 22,
              fontWeight: FontWeight.bold,
            ),
          ),
          if (front != null && back != null) ...[
            const SizedBox(height: 4),
            Text(
              "F ${front.toStringAsFixed(1)}  B ${back.toStringAsFixed(1)}",
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildCenteringRow(
    Map<String, dynamic> frontCentering,
    Map<String, dynamic> constraints,
  ) {
    final meas = frontCentering['measurements'] is Map
        ? Map<String, dynamic>.from(frontCentering['measurements'] as Map)
        : <String, dynamic>{};
    final lrRatio = meas['left_right_ratio']?.toString() ?? '?/?';
    final tbRatio = meas['top_bottom_ratio']?.toString() ?? '?/?';
    final capActive = constraints['centering_cap_activated'] == true;
    final cap = frontCentering['centering_cap'];
    final method = frontCentering['detection_method']?.toString() ?? '';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.white12),
      ),
      child: Row(
        children: [
          const Icon(Icons.crop_free, color: Colors.white38, size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  "Centering",
                  style: TextStyle(color: Colors.white54, fontSize: 12),
                ),
                const SizedBox(height: 2),
                Text(
                  "H $lrRatio   V $tbRatio",
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
                if (method.isNotEmpty)
                  Text(
                    "via $method",
                    style: const TextStyle(color: Colors.white24, fontSize: 10),
                  ),
              ],
            ),
          ),
          if (capActive)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: Colors.orange.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: Colors.orange.withValues(alpha: 0.6)),
              ),
              child: Text(
                "Cap PSA $cap",
                style: const TextStyle(color: Colors.orange, fontSize: 11),
              ),
            ),
        ],
      ),
    );
  }

  bool _hasConstraints(Map<String, dynamic> constraints) {
    return constraints['damage_cap_activated'] == true ||
        constraints['floor_activated'] == true ||
        constraints['ceiling_activated'] == true ||
        constraints['half_point_qualified'] == true;
  }

  Widget _buildConstraintsPanel(Map<String, dynamic> constraints) {
    final items = <String>[];
    if (constraints['damage_cap_activated'] == true) {
      final reason =
          constraints['damage_cap_reason']?.toString() ?? 'damage';
      items.add('Grade capped: $reason');
    }
    if (constraints['floor_activated'] == true) {
      items.add('Grade floor applied (weakest dimension pulled grade down)');
    }
    if (constraints['ceiling_activated'] == true) {
      items.add('Grade ceiling applied');
    }
    if (constraints['half_point_qualified'] == true) {
      items.add('Half-point grade qualified');
    }

    if (items.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.orange.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            "Grading Adjustments",
            style: TextStyle(
              color: Colors.orange,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          ...items.map((s) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  children: [
                    const Icon(Icons.adjust, color: Colors.orange, size: 14),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        s,
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              )),
        ],
      ),
    );
  }

  Widget _buildDefectList(List<dynamic> defects) {
    if (defects.isEmpty) return const SizedBox.shrink();

    // Group by section
    final Map<String, List<Map<String, dynamic>>> grouped = {
      'Front Corners': [],
      'Front Edges': [],
      'Back Corners': [],
      'Back Edges': [],
      'Surface': [],
    };

    for (final d in defects) {
      if (d is! Map) continue;
      final loc = d['location']?.toString() ?? '';
      if (loc.startsWith('front') && loc.contains('corner')) {
        grouped['Front Corners']!.add(Map<String, dynamic>.from(d));
      } else if (loc.startsWith('front') && loc.contains('edge')) {
        grouped['Front Edges']!.add(Map<String, dynamic>.from(d));
      } else if (loc.startsWith('back') && loc.contains('corner')) {
        grouped['Back Corners']!.add(Map<String, dynamic>.from(d));
      } else if (loc.startsWith('back') && loc.contains('edge')) {
        grouped['Back Edges']!.add(Map<String, dynamic>.from(d));
      } else {
        grouped['Surface']!.add(Map<String, dynamic>.from(d));
      }
    }

    final nonEmpty = grouped.entries.where((e) => e.value.isNotEmpty).toList();
    if (nonEmpty.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          "Defects Found",
          style: TextStyle(
            color: Colors.white,
            fontSize: 17,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 10),
        ...nonEmpty.map((entry) => _buildDefectGroup(entry.key, entry.value)),
      ],
    );
  }

  Widget _buildDefectGroup(
      String section, List<Map<String, dynamic>> items) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          section,
          style: const TextStyle(
            color: Colors.white54,
            fontSize: 12,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.5,
          ),
        ),
        const SizedBox(height: 6),
        ...items.map((d) => _buildDefectItem(d)),
        const SizedBox(height: 14),
      ],
    );
  }

  Widget _buildDefectItem(Map<String, dynamic> defect) {
    final loc = (defect['location']?.toString() ?? '')
        .replaceAll('_', ' ')
        .replaceAll(' corner', '')
        .replaceAll(' edge', '')
        .trim();
    final desc = defect['description']?.toString() ?? 'wear detected';
    final severity = defect['severity']?.toString() ?? 'minor';
    final sevColor = severity == 'severe'
        ? Colors.redAccent
        : severity == 'moderate'
            ? Colors.orange
            : Colors.yellow.shade700;

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 8,
            height: 8,
            margin: const EdgeInsets.only(top: 4, right: 8),
            decoration: BoxDecoration(color: sevColor, shape: BoxShape.circle),
          ),
          Expanded(
            child: Text(
              "${loc.isNotEmpty ? '${_titleCase(loc)}: ' : ''}$desc",
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
          ),
          const SizedBox(width: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
            decoration: BoxDecoration(
              color: sevColor.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(4),
            ),
            child: Text(
              severity,
              style: TextStyle(color: sevColor, fontSize: 10),
            ),
          ),
        ],
      ),
    );
  }

  String _titleCase(String s) =>
      s.split(' ').map((w) => w.isEmpty ? '' : '${w[0].toUpperCase()}${w.substring(1)}').join(' ');

  Color _getScoreColor(double score) {
    if (score >= 8.5) return Colors.green;
    if (score >= 6.5) return Colors.orange;
    return Colors.redAccent;
  }
}
