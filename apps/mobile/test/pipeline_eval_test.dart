import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lifeline_mobile/engine/bm25.dart';
import 'package:lifeline_mobile/engine/embedder.dart';
import 'package:lifeline_mobile/engine/knowledge_pack.dart';
import 'package:lifeline_mobile/engine/models.dart';
import 'package:lifeline_mobile/engine/pipeline.dart';
import 'package:lifeline_mobile/engine/semantic_cache.dart';
import 'package:lifeline_mobile/engine/vector_store.dart';
import 'package:qdrant_edge/qdrant_edge.dart' show SparseVector;

/// Query vectors produced by the backend's model, so this test isolates the Dart
/// retrieval/gate/safety/cache logic running on the real Qdrant Edge engine.
class FixtureEmbedder implements Embedder {
  FixtureEmbedder(this.vectors);
  final Map<String, Float32List> vectors;
  @override
  String get modelId => 'BAAI/bge-small-en-v1.5';
  @override
  Future<Float32List> embed(String text) async =>
      vectors[text] ?? (throw StateError('no fixture vector for "$text" - rerun scripts/build_mobile_pack.py'));
  @override
  Future<void> dispose() async {}
}

void main() {
  final fixtures = jsonDecode(File('test/fixtures/parity.json').readAsStringSync()) as Map<String, dynamic>;
  final pack = KnowledgePack.parse(File('assets/knowledge/pack.json').readAsStringSync());
  final embedder = FixtureEmbedder((fixtures['query_vectors'] as Map<String, dynamic>)
      .map((k, v) => MapEntry(k, decodeF32(v as String))));
  final bm25 = Bm25(stopwords: pack.stopwords);
  late Directory dir;
  late EdgeVectorStore store;
  late EmergencyPipeline pipeline;
  late EvidenceStateSemanticCache cache;
  final incidentVersions = <String, int>{};
  final profile = pack.defaultProfile;

  setUpAll(() async {
    dir = Directory.systemTemp.createTempSync('lifeline_pipeline_test_');
    store = await EdgeVectorStore.open(
        root: dir.path, embedder: embedder, bm25: bm25, dim: 384, schemaVersion: pack.config.schemaVersion);
    for (final p in pack.protocols) {
      await store.upsert(p.item,
          precomputed: [for (final c in p.chunks) c.vector],
          docSparse: SparseVector(indices: p.bm25Indices, values: p.bm25Values));
    }
    cache = EvidenceStateSemanticCache(pack.config, hashResolver: store.currentHash);
    pipeline = EmergencyPipeline(
      store: store,
      embedder: embedder,
      bm25: bm25,
      config: pack.config,
      cache: cache,
      incidentVersion: (id) => incidentVersions[id] ?? 0,
      incidents: (_) => const [],
    );
  });

  tearDownAll(() {
    store.close();
    dir.deleteSync(recursive: true);
  });

  test('qdrant edge shard holds the knowledge pack', () {
    expect(store.list(MemoryTier.trusted), hasLength(12));
    expect(store.count(MemoryTier.trusted), 12 + pack.protocols.fold<int>(0, (n, p) => n + p.chunks.length));
  });

  test('every eval case routes to the expected protocol or abstains', () async {
    final failures = <String>[];
    for (final c in (fixtures['eval_cases'] as List).cast<Map<String, dynamic>>()) {
      final r = await pipeline.process(c['q'] as String, profile: profile, allowCache: false);
      final got = r.verdict == Verdict.insufficient ? null : r.citations.first.evidenceId;
      final ok = got == c['expected'] || ((c['also_ok'] as List?) ?? const []).contains(got);
      if (!ok) failures.add('${c['q']} -> $got (conf ${r.confidence.toStringAsFixed(3)})');
    }
    expect(failures, isEmpty, reason: failures.join('\n'));
  });

  test('aspirin is withheld for the allergic owner but not for "my father"', () async {
    final own = await pipeline.process('Can I give the patient Aspirin for chest pain?', profile: profile, allowCache: false);
    expect(own.verdict, Verdict.conflict);
    expect(own.immediateActions.any((a) => a.toLowerCase().contains('aspirin')), isFalse);
    expect(own.warnings.any((w) => w.startsWith('DO NOT GIVE ASPIRIN')), isTrue);

    final father = await pipeline.process('my father has crushing chest pain', profile: profile, allowCache: false);
    expect(father.verdict, Verdict.sufficient);
    expect(father.warnings.any((w) => w.contains('NOT applied')), isTrue);
  });

  test('infant choking replaces the adult technique', () async {
    final r = await pipeline.process('my 8 month old baby is choking on a grape', profile: profile, allowCache: false);
    expect(r.ageCategory, 'infant');
    expect(r.immediateActions.any((a) => a.contains('5 chest thrusts with 2 fingers')), isTrue);
    expect(r.immediateActions.any((a) => a.toLowerCase().contains('abdominal thrust')), isFalse);
  });

  test('full protocol steps are returned (no truncation)', () async {
    final r = await pipeline.process('where do I inject the epipen', profile: profile, allowCache: false);
    expect(r.immediateActions, hasLength(7));
  });

  test('semantic cache: hit, safety-term guard, and incident invalidation', () async {
    cache.clear();
    const q = 'adult collapsed and is not breathing';
    final first = await pipeline.process(q, profile: profile, incidentId: 'i1');
    final second = await pipeline.process('Adult collapsed and is not breathing.', profile: profile, incidentId: 'i1');
    expect(first.cacheHit, isFalse);
    expect(second.cacheHit, isTrue);

    await pipeline.process('the patient is unconscious and breathing', profile: profile);
    final neg = await pipeline.process('the patient is unconscious and not breathing', profile: profile);
    expect(neg.cacheHit, isFalse);

    incidentVersions['i1'] = 1;
    final third = await pipeline.process(q, profile: profile, incidentId: 'i1');
    expect(third.cacheHit, isFalse);
  });

  test('profile questions are answered from the vault', () async {
    final r = await pipeline.process('what is my blood type', profile: profile);
    expect(r.retrievalMode, 'profile');
    expect(r.immediateActions.first, contains('O-'));
  });
}
