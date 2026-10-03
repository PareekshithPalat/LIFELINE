import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:lifeline_mobile/engine/knowledge_pack.dart';
import 'package:lifeline_mobile/engine/models.dart';
import 'package:lifeline_mobile/lifeline.dart';
import 'package:lifeline_mobile/main.dart';

import 'fixtures.g.dart';

/// Runs on a real device / emulator / desktop: real ONNX Runtime + real Qdrant Edge.
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  late Directory dir;
  late Lifeline app;

  setUpAll(() async {
    dir = Directory.systemTemp.createTempSync('lifeline_it_');
    app = await Lifeline.open(baseDir: dir.path);
  });

  tearDownAll(() {
    app.dispose();
    dir.deleteSync(recursive: true);
  });

  testWidgets('on-device ONNX embeddings match the backend model', (tester) async {
    expect(app.denseReady, isTrue, reason: app.embedderError);
    final embedder = app.embedder!;
    for (final MapEntry(key: q, value: b64) in backendQueryVectors.entries) {
      final want = decodeF32(b64);
      final got = await embedder.embed(q);
      var dot = 0.0;
      for (var i = 0; i < want.length; i++) {
        dot += want[i] * got[i];
      }
      expect(dot, greaterThan(0.999), reason: 'cosine(device, backend) for "$q"');
    }
  });

  testWidgets('every eval case is answered correctly on-device', (tester) async {
    final failures = <String>[];
    final latencies = <double>[];
    for (final c in (jsonDecode(evalCasesJson) as List).cast<Map<String, dynamic>>()) {
      final r = await app.ask(c['q'] as String, allowCache: false);
      latencies.add(r.latencyMs);
      final got = r.verdict == Verdict.insufficient ? null : r.citations.first.evidenceId;
      final ok = got == c['expected'] || ((c['also_ok'] as List?) ?? const []).contains(got);
      if (!ok) failures.add('${c['q']} -> $got');
    }
    latencies.sort();
    // ignore: avoid_print
    print('on-device latency: median ${latencies[latencies.length ~/ 2].toStringAsFixed(1)} ms, '
        'p95 ${latencies[(latencies.length * 0.95).floor()].toStringAsFixed(1)} ms, '
        'max ${latencies.reduce(math.max).toStringAsFixed(1)} ms');
    expect(failures, isEmpty, reason: failures.join('\n'));
  });

  testWidgets('cached repeat is served from the evidence-state cache', (tester) async {
    app.cache.clear();
    final first = await app.ask('Adult collapsed and is not breathing');
    final second = await app.ask('Adult collapsed and is not breathing');
    expect(first.cacheHit, isFalse);
    expect(second.cacheHit, isTrue);
    expect(second.latencyMs, lessThan(first.latencyMs));
  });

  testWidgets('UI: a one-tap scenario shows the verified protocol', (tester) async {
    await tester.pumpWidget(const LifelineApp());
    for (var i = 0; i < 300 && find.text('Not breathing').evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    await tester.tap(find.text('Not breathing'));
    for (var i = 0; i < 100 && find.text('VERIFIED PROTOCOL').evaluate().isEmpty; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
    expect(find.text('VERIFIED PROTOCOL'), findsOneWidget);
    expect(find.textContaining('Adult Cardiopulmonary Resuscitation'), findsWidgets);
    expect(find.byType(FilledButton), findsWidgets);
  });
}
