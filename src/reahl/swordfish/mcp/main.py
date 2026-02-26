from reahl.swordfish.main import run_application as run_swordfish_application


def run_application():
    run_swordfish_application(default_mode='mcp-headless')


if __name__ == '__main__':
    run_application()
