from blinker import Signal

on_terminal_auth = Signal()
on_first_terminal_add = Signal()
on_request_to_app = Signal()
on_peer_write = Signal()
on_peer_auth = Signal()
