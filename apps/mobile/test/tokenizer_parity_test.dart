import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lifeline_mobile/engine/wordpiece.dart';
import 'dart:convert';

void main() {
  final fixtures = jsonDecode(File('test/fixtures/parity.json').readAsStringSync()) as Map<String, dynamic>;
  final tok = WordPieceTokenizer.fromTokenizerJson(File('assets/models/tokenizer.json').readAsStringSync());

  test('token ids match the HuggingFace tokenizer used by the backend', () {
    for (final c in (fixtures['tokenizer'] as List).cast<Map<String, dynamic>>()) {
      expect(tok.encode(c['text'] as String), (c['ids'] as List).cast<int>(), reason: c['text'] as String);
    }
  });
}
