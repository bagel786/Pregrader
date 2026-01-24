import 'package:dio/dio.dart';
import '../core/network/api_client.dart';

class PokemonService {
  final Dio _dio = ApiClient().dio;

  Future<Map<String, dynamic>> searchCards(
    String query, {
    int page = 1,
    int pageSize = 20,
  }) async {
    try {
      final response = await _dio.get(
        '/cards/search',
        queryParameters: {'q': query, 'page': page, 'page_size': pageSize},
      );
      return response.data;
    } catch (e) {
      if (e is DioException) {
        throw Exception(e.message ?? 'Failed to search cards');
      }
      throw Exception('Failed to search cards: $e');
    }
  }

  Future<Map<String, dynamic>> getCard(String id) async {
    try {
      final response = await _dio.get('/cards/$id');
      return response.data;
    } catch (e) {
      throw Exception('Failed to get card: $e');
    }
  }
}
