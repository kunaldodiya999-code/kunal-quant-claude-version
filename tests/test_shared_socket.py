"""One FYERS connection shared by the index sessions."""

from paper_trading.shared_socket import SharedSocketHub


class RealSocket:
    instances = []

    def __init__(self, **callbacks):
        self.cb, self.subs, self.closed = callbacks, [], 0
        RealSocket.instances.append(self)

    def connect(self):
        self.cb["on_connect"]()

    def subscribe(self, symbols, data_type):
        self.subs.append((tuple(symbols), data_type))

    def close_connection(self):          # the FYERS SDK name
        self.closed += 1


def make(hub, symbol, log):
    socket = hub.factory(on_message=lambda m: log.append((symbol, m["symbol"])),
                         on_connect=lambda: socket.subscribe([symbol]))
    return socket


def test_messages_reach_only_the_subscriber_and_one_real_connection():
    RealSocket.instances.clear()
    hub, log = SharedSocketHub(RealSocket), []
    a, b = make(hub, "NSE:NIFTY50-INDEX", log), make(hub, "BSE:SENSEX-INDEX", log)
    a.connect()
    b.connect()                              # hub already connected: b subscribes at once
    real = RealSocket.instances[0]
    assert len(RealSocket.instances) == 1
    assert [s for s, _ in real.subs] == [("NSE:NIFTY50-INDEX",), ("BSE:SENSEX-INDEX",)]
    real.cb["on_message"]({"symbol": "BSE:SENSEX-INDEX", "ltp": 1})
    real.cb["on_message"]({"symbol": "NSE:NIFTY50-INDEX", "ltp": 1})
    assert log == [("BSE:SENSEX-INDEX", "BSE:SENSEX-INDEX"), ("NSE:NIFTY50-INDEX", "NSE:NIFTY50-INDEX")]


def test_reconnect_resubscribes_everyone_and_close_happens_once_at_the_end():
    RealSocket.instances.clear()
    hub, log = SharedSocketHub(RealSocket), []
    a, b = make(hub, "X", log), make(hub, "Y", log)
    a.connect(); b.connect()
    real = RealSocket.instances[0]
    real.subs.clear()
    real.cb["on_connect"]()                  # FYERS reconnect: the SDK forgot all subscriptions
    assert real.subs == [(("X", "Y"), "SymbolUpdate")]       # everything sent again, once
    a.close()
    assert real.closed == 0
    b.close()
    assert real.closed == 1


def test_paper_feed_close_uses_the_fyers_close_connection():
    from paper_trading.fyers_feed import FyersPaperFeed
    from market_data.fyers_quote_cache import FyersQuoteCache
    from paper_trading.market_data_pipeline import PaperMarketDataPipeline
    RealSocket.instances.clear()
    feed = FyersPaperFeed(client=object(), pipeline=PaperMarketDataPipeline(), quote_cache=FyersQuoteCache(),
                          underlying_symbols=["NSE:NIFTY50-INDEX"], socket_factory=RealSocket)
    feed.start()
    feed.close()
    assert RealSocket.instances[0].closed == 1
