"""Shared pytest configuration for EAB tests."""


def pytest_addoption(parser):
    parser.addoption(
        "--hw",
        action="store_true",
        default=False,
        help="Run hardware-in-the-loop tests (requires debug probe connected)",
    )
