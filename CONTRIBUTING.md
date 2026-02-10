# Contributing to Embedded Agent Bridge

Thanks for your interest in contributing!

## How to Contribute

1. **Report bugs** — Open an [issue](https://github.com/shanemmattner/embedded-agent-bridge/issues) with steps to reproduce
2. **Suggest features** — Open an issue describing the use case
3. **Submit PRs** — Fork the repo, make changes, open a pull request

## Development Setup

```bash
git clone https://github.com/shanemmattner/embedded-agent-bridge.git
cd embedded-agent-bridge
pip install -e ".[dev]"
pytest
```

## Code Style

- Python 3.9+
- Keep it simple — this project values readability over cleverness
- Add tests for new functionality

## Testing

```bash
pytest                    # Run all tests
pytest -x                 # Stop on first failure
pytest eab/tests/         # Unit tests only
pytest tests/             # CLI integration tests only
```

## Questions?

Open an issue or start a discussion. We're happy to help.
