import logging
import time
import argparse

from PyQt5 import QtCore, QtWidgets, QtGui

from . import fakes, widgets, token_fetcher
from .config import Config

LOGGER = logging.getLogger("app")

logging.basicConfig(level=logging.DEBUG)

cache = {}

SESSION = None
def get_session(refresh=False):
    global SESSION
    if not SESSION or refresh:
        import botocore.session
        SESSION = botocore.session.Session()
    return SESSION

def get_config_loader(parser, args):
    if args.fake_config:
        import botocore.configloader
        config_data = botocore.configloader.load_config(args.fake_config)
        return fakes.get_config_loader(config_data['profiles'])
    def config_loader():
        session = get_session(refresh=True)
        return session.full_config['profiles']
    return config_loader

def get_token_fetcher_kwargs(parser, args):
    kwargs = {}
    if args.token_fetcher_controls:
        controls = fakes.ControlsWidget()
        if args.fake_token_fetcher:
            kwargs['delay'] = controls.delay
    else:
        controls = None
        if args.fake_token_fetcher:
            kwargs['delay'] = 20
    kwargs['on_pending_authorization'] = token_fetcher.on_pending_authorization
    return kwargs, controls

def get_token_fetcher_creator(parser, args):
    kwargs, controls = get_token_fetcher_kwargs(parser, args)
    if args.fake_token_fetcher:
        token_fetcher_creator = fakes.get_token_fetcher_creator(**kwargs)
    else:
        kwargs['session'] = get_session()
        token_fetcher_creator = token_fetcher.get_token_fetcher_creator(**kwargs)
    return token_fetcher_creator, controls

def initialize(parser, app, config_loader, token_fetcher_creator, time_fetcher=None):
    icon = QtGui.QIcon("sso-icon.png")

    app.setWindowIcon(icon)

    thread = QtCore.QThread()

    config = Config(config_loader, token_fetcher_creator, time_fetcher=time_fetcher, session_fetcher=get_session)

    config.moveToThread(thread)

    thread.started.connect(config.reload)

    window = widgets.AWSSSOLoginWindow(config)
    tray_icon = widgets.AWSSSOLoginTrayIcon(icon, config)

    return config, thread, window, tray_icon

class ThreadIdLogger(QtCore.QObject):
    def __init__(self, thread_name):
        super().__init__()
        self.thread_name = thread_name

    def log_id(self):
        LOGGER.debug('%s thread id: %i', self.thread_name, int(QtCore.QThread.currentThreadId()))

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument('--log-level', '-l', choices=['DEBUG', 'INFO'])

    parser.add_argument('--fake-config')

    parser.add_argument('--fake-token-fetcher', action='store_true')

    parser.add_argument('--token-fetcher-controls', action='store_true')

    args = parser.parse_args()

    log_kwargs = {}
    if args.log_level:
        log_kwargs['level'] = getattr(logging, args.log_level)
    logging.basicConfig(**log_kwargs)

    app = QtWidgets.QApplication([])

    config_loader = get_config_loader(parser, args)

    token_fetcher_creator, controls = get_token_fetcher_creator(parser, args)

    time_fetcher = None
    if controls:
        time_fetcher = controls.get_time

    config, thread, window, tray_icon = initialize(parser, app, config_loader, token_fetcher_creator, time_fetcher=time_fetcher)

    window.show()
    tray_icon.show()

    if controls:
        controls.time_changed.connect(config.update_timers)
        controls.setParent(window, QtCore.Qt.Window)
        controls.show()


    ThreadIdLogger("main").log_id()
    worker_thread_logger = ThreadIdLogger("worker")
    worker_thread_logger.moveToThread(thread)
    thread.started.connect(worker_thread_logger.log_id)

    thread.start()

    def on_close():
        LOGGER.debug('on_close')
        thread.terminate()

    app.lastWindowClosed.connect(on_close)

    return app.exec_()
