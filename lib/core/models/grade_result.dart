class GradeResult {
  final double centeringScore;
  final double surfaceScore;
  final double cornerScore;
  final double edgeScore;
  final double finalGrade;

  GradeResult({
    required this.centeringScore,
    required this.surfaceScore,
    required this.cornerScore,
    required this.edgeScore,
  }) : finalGrade =
           (centeringScore + surfaceScore + cornerScore + edgeScore) / 4;

  @override
  String toString() {
    return 'Grade: ${finalGrade.toStringAsFixed(1)} '
        '(C:${centeringScore.toStringAsFixed(1)} '
        'Cr:${cornerScore.toStringAsFixed(1)} '
        'E:${edgeScore.toStringAsFixed(1)} '
        'S:${surfaceScore.toStringAsFixed(1)})';
  }
}
