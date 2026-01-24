import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pregrader/main.dart';

void main() {
  testWidgets('App smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const PokemonPregraderApp());

    // Verify that the title text is present.
    expect(find.text('Scan a Card to Start'), findsOneWidget);
    expect(find.byIcon(Icons.camera_alt_outlined), findsOneWidget);
    expect(find.byIcon(Icons.add_a_photo), findsOneWidget);
  });
}
