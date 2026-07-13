# Contributing

Contributions are welcome! Here's how to help:

## Reporting Issues

- Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) for bugs
- Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md) for ideas
- Check existing issues before creating new ones

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-improvement`)
3. Test your changes by installing the skill locally:
   ```bash
   cp -r skills/grow-vines ~/.claude/skills/grow-vines
   python ~/.claude/skills/grow-vines/scripts/fetch_assets.py
   ```
4. Run a smoke generation and the independent verify (see SKILL.md), and
   confirm `INDEP_VERIFY: PASS`
5. Commit your changes with a clear message
6. Open a pull request using the [PR template](.github/pull_request_template.md)

## Guidelines

- Keep the skill's voice and structure consistent
- `scripts/plantgen/` is the proven generator core - behavioral changes there
  need a before/after render or a verify log in the PR
- Don't add hard dependencies - BagaIvy stays optional, the procedural
  fallback must keep working
- Update the CHANGELOG.md with your changes

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
