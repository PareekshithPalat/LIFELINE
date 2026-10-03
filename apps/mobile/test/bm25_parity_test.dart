import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lifeline_mobile/engine/bm25.dart';

void main() {
  final fixtures = jsonDecode(File('test/fixtures/parity.json').readAsStringSync()) as Map<String, dynamic>;
  final pack = jsonDecode(File('assets/knowledge/pack.json').readAsStringSync()) as Map<String, dynamic>;
  final bm25 = Bm25(stopwords: (pack['stopwords'] as List).cast<String>());

  test('murmur3 matches reference values', () {
    expect(bm25.tokenId('cardiac'), 498930136);
    expect(bm25.tokenId('arrest'), 545582287);
    expect(bm25.tokenId('run'), 243905464);
  });

  test('every vocabulary word maps to the same token ids as qdrant-edge', () {
    final words = (fixtures['bm25_words'] as Map<String, dynamic>);
    final mismatches = <String>[];
    words.forEach((w, ids) {
      final got = bm25.embedQuery(w).indices;
      if (got.join(',') != (ids as List).join(',')) mismatches.add('$w: $got != $ids');
    });
    expect(mismatches, isEmpty, reason: mismatches.take(20).join('\n'));
    expect(words.length, greaterThan(300));
  });

  test('query vectors match for full queries and tricky text', () {
    for (final c in (fixtures['bm25_queries'] as List).cast<Map<String, dynamic>>()) {
      expect(bm25.embedQuery(c['text'] as String).indices, c['indices'], reason: c['text'] as String);
    }
  });

  test('document vectors match term-frequency weights', () {
    for (final c in (fixtures['bm25_documents'] as List).cast<Map<String, dynamic>>()) {
      final got = bm25.embedDocument(c['text'] as String);
      final want = Map.fromIterables((c['indices'] as List).cast<num>().map((e) => e.toInt()),
          (c['values'] as List).cast<num>().map((e) => e.toDouble()));
      expect(got.indices.toSet(), want.keys.toSet());
      for (var i = 0; i < got.indices.length; i++) {
        expect(got.values[i], closeTo(want[got.indices[i]]!, 1e-4));
      }
    }
  });
}
