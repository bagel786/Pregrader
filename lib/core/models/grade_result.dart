class GradeResult {
  final double centeringScore;
  final double surfaceScore;
  final double cornerScore;
  final double edgeScore;
  final double finalGrade;

  GradeResult({
    required this.centeringScore,
    this.surfaceScore = 10.0, // Default for now
    this.cornerScore = 10.0,
    this.edgeScore = 10.0,
  }) : finalGrade =
           (centeringScore + surfaceScore + cornerScore + edgeScore) / 4;

  @override
  String toString() {
    return 'Grade: ${finalGrade.toStringAsFixed(1)} (Centering: ${centeringScore.toStringAsFixed(1)})';
  }
}
