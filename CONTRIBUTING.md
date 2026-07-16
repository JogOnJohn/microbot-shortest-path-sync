# Contributing

Keep changes deterministic, reviewable, and parser-aware.

Before submitting a change:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

For a real sync, also run the tool against a Microbot checkout and review both generated reports.
Changes that affect generated transport resources should then pass Microbot's:

```powershell
.\gradlew.bat :client:validateTransportSync --console=plain
.\gradlew.bat :client:runUnitTests `
  --tests net.runelite.client.plugins.microbot.shortestpath.ShortestPathGoldenRouteBaselineTest `
  --tests net.runelite.client.plugins.microbot.shortestpath.TransportResourceLoadTest `
  --console=plain
```

Guidelines:

- never silently ignore an unknown upstream column or category;
- keep raw TSV parsing aligned with Microbot's Java parser;
- protect locally tuned durations unless deliberately reviewed;
- add a fixture and test for converter defects;
- keep one upstream category adoption per commit when transport data changes;
- do not bundle Microbot runtime changes into this repository.
