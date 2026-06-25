import os


def pytest_addoption(parser):
    parser.addoption(
        '--gemstone-version',
        default=None,
        help='GemStone version to test against (e.g. 3.6.5). Sets GEMSTONE to the matching '
             'installation under /opt/gemstone/. Without this option, GEMSTONE is used as set '
             'by the shell environment.',
    )


def pytest_configure(config):
    version = config.getoption('--gemstone-version', default=None)
    if version is None:
        return
    installation = f'/opt/gemstone/GemStone64Bit{version}-x86_64.Linux'
    if not os.path.isdir(installation):
        raise ValueError(f'GemStone {version} not found at {installation}')
    os.environ['GEMSTONE'] = installation
