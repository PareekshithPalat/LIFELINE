import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:lifeline_mobile/engine/embedder.dart';
import 'package:lifeline_mobile/engine/models.dart';
import 'package:lifeline_mobile/lifeline.dart';

/// Deterministic stand-in for the ONNX model (personal/incident chunks only need *a*
/// vector here; protocol vectors come precomputed from the knowledge pack).
class HashEmbedder implements Embedder {
  @override
  String get modelId => 'BAAI/bge-small-en-v1.5';
  @override
  Future<Float32List> embed(String text) async {
    final v = List<double>.generate(384, (i) => ((text.hashCode * (i + 7)) % 997) / 997.0 - 0.5);
    return l2normalize(v);
  }

  @override
  Future<void> dispose() async {}
}

/// End-to-end: the Flutter app's sync client against the real Python hub (apps/api).
void main() {
  // Assets come from the test binding; that binding also fakes every HTTP request with a
  // 400, so real networking is restored for this end-to-end test.
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null;
  final repo = Directory.current.parent.parent.path;
  final python = Platform.isWindows ? '$repo\\.venv\\Scripts\\python.exe' : '$repo/.venv/bin/python';
  final available = File(python).existsSync() && Platform.environment['LIFELINE_SKIP_HUB_TEST'] == null;

  late Process hub;
  late String url;
  late Directory dir;
  late Lifeline app;

  setUpAll(() async {
    if (!available) return;
    final socket = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final port = socket.port;
    await socket.close();
    url = 'http://127.0.0.1:$port';
    final runtime = Directory.systemTemp.createTempSync('lifeline_hub_');
    hub = await Process.start(python, ['-m', 'uvicorn', 'apps.api.main:app', '--port', '$port', '--log-level', 'warning'],
        workingDirectory: repo,
        environment: {
          'QDRANT_MEMORY_MODE': 'true',
          'LIFELINE_RUNTIME_DIR': runtime.path,
          'LIFELINE_NODE_ID': 'hub_node',
          'LIFELINE_API_KEY': 'phone-key',
          'LIFELINE_ADMIN_KEY': 'hub-admin',
          'FASTEMBED_CACHE_PATH': '$repo${Platform.pathSeparator}data${Platform.pathSeparator}models',
        });
    hub.stderr.transform(utf8.decoder).listen((_) {});
    hub.stdout.transform(utf8.decoder).listen((_) {});
    for (var i = 0; i < 240; i++) {
      try {
        if ((await http.get(Uri.parse('$url/api/system/health'))).statusCode == 200) break;
      } catch (_) {}
      await Future<void>.delayed(const Duration(milliseconds: 500));
    }
    dir = Directory.systemTemp.createTempSync('lifeline_phone_');
    app = await Lifeline.open(baseDir: dir.path, embedderOverride: HashEmbedder());
    app.updateSettings(hubUrl: url, apiKey: 'phone-key', networkEnabled: true);
  });

  tearDownAll(() {
    if (!available) return;
    hub.kill();
    app.dispose();
  });

  Map<String, String> h({bool admin = false}) =>
      {'X-API-Key': 'phone-key', 'Content-Type': 'application/json', if (admin) 'X-Admin-Key': 'hub-admin'};

  test('wrong API key is reported, not silently ignored', () async {
    app.updateSettings(apiKey: 'wrong');
    expect((await app.sync()).status, 'UNAUTHORIZED');
    app.updateSettings(apiKey: 'phone-key');
  }, skip: !available);

  test('phone -> hub: an observation logged offline reaches the hub', () async {
    app.updateSettings(networkEnabled: false);
    final obs = await app.logObservation(IncidentObservation(
        incidentId: 'scene-7', vitalSigns: {'pulse': '120 bpm'}, observedSymptoms: ['pale']));
    expect((await app.sync()).status, 'OFFLINE');
    expect(app.pendingSync, 1);

    app.updateSettings(networkEnabled: true);
    final outcome = await app.sync();
    expect(outcome.status, 'ONLINE_SYNCED', reason: outcome.message);
    expect(outcome.pushed, 1);
    expect(app.pendingSync, 0);
    final res = await http.get(Uri.parse('$url/api/memory/incident?incident_id=scene-7'), headers: h());
    final hubObs = (jsonDecode(res.body) as List).cast<Map<String, dynamic>>();
    expect(hubObs.single['id'], obs.id);
    expect(hubObs.single['origin_node'], app.settings.nodeId);
  }, skip: !available);

  test('both directions: concurrent allergy edits converge (SAFETY_MAXIMUM)', () async {
    final hubProfile = jsonDecode((await http.get(Uri.parse('$url/api/memory/personal'), headers: h())).body)
        as Map<String, dynamic>;
    (hubProfile['allergies'] as List).add('Latex');
    expect((await http.put(Uri.parse('$url/api/memory/personal'), headers: h(), body: jsonEncode(hubProfile)))
        .statusCode, 200);

    final local = app.profile..allergies.add('Shellfish');
    await app.saveProfile(local);
    expect((await app.sync()).status, 'ONLINE_SYNCED');

    final phone = app.profile.allergies.map((a) => a.toLowerCase()).toSet();
    expect(phone.containsAll({'latex', 'shellfish', 'aspirin'}), isTrue, reason: '$phone');
    final hubNow = jsonDecode((await http.get(Uri.parse('$url/api/memory/personal'), headers: h())).body) as Map;
    final hubAllergies = (hubNow['allergies'] as List).map((a) => '$a'.toLowerCase()).toSet();
    expect(hubAllergies.containsAll({'latex', 'shellfish'}), isTrue, reason: '$hubAllergies');

    // The new allergy now protects the patient on the phone.
    final r = await app.ask('can I give him a peanut butter sandwich and shrimp', allowCache: false);
    expect(r.warnings.any((w) => w.contains('SHRIMP')), isTrue, reason: r.warnings.join('\n'));
  }, skip: !available);

  test('hub -> phone: a newer trusted protocol revision is indexed on the phone', () async {
    final protocols = (jsonDecode((await http.get(Uri.parse('$url/api/memory/trusted'), headers: h())).body) as List)
        .cast<Map<String, dynamic>>();
    final burn = protocols.firstWhere((p) => p['id'] == 'burns-thermal-chemical-01');
    burn['version'] = (burn['version'] as int) + 3;
    burn['content'] = '${burn['content']}\nStep 7: Hub revision - remove contact lenses after chemical eye burns.';
    final res =
        await http.post(Uri.parse('$url/api/memory/trusted'), headers: h(admin: true), body: jsonEncode(burn));
    expect(res.statusCode, 200, reason: res.body);

    expect((await app.sync()).pulled, greaterThanOrEqualTo(1));
    expect(app.trusted.get('burns-thermal-chemical-01')!.version, burn['version']);
    final indexed = app.store.get(MemoryTier.trusted, 'burns-thermal-chemical-01')!;
    expect(indexed.content, contains('Hub revision'));

    final again = await app.sync();
    expect((again.pushed, again.pulled), (0, 0));
  }, skip: !available);
}
