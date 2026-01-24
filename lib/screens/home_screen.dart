import 'package:flutter/material.dart';
import '../widgets/pokeball_widget.dart';
import '../core/routes/app_routes.dart';
import '../services/pokemon_service.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Spacer(),
            PokeballWidget(
              size: 200,
              onTap: () {
                Navigator.of(context).pushNamed(AppRoutes.cameraCapture);
              },
            ),
            const SizedBox(height: 32),
            OutlinedButton(
              onPressed: () async {
                try {
                  final service = PokemonService();
                  final result = await service.searchCards('charizard');
                  print('Search Result: ${result['totalCount']} cards found');
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(
                          'Success! Found ${result['totalCount']} "Charizard" cards',
                        ),
                      ),
                    );
                  }
                } catch (e) {
                  print('Error: $e');
                  if (context.mounted) {
                    ScaffoldMessenger.of(
                      context,
                    ).showSnackBar(SnackBar(content: Text('Error: $e')));
                  }
                }
              },
              child: const Text('Test Backend Connection'),
            ),
            const SizedBox(height: 16),
            Text(
              'Tap to Start',
              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                color: Colors.grey[600],
                fontWeight: FontWeight.w300,
                letterSpacing: 1.5,
              ),
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.only(bottom: 32.0),
              child: Text(
                'Pokemon Pregrader',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: Colors.grey[400]),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
