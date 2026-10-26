from copybot.solana_rpc import RpcError, SolanaRpc


class _Rpc(SolanaRpc):
    def __init__(self):
        self.max_tx_version = 0
        self.seen_versions = []

    async def call(self, method, params=None, **_):
        version = params[1]["maxSupportedTransactionVersion"]
        self.seen_versions.append(version)
        if version < 1:
            raise RpcError(method, {"code": -32015, "message": 'Transaction version (1) is not supported by the '
                                    'requesting client. Please try the request again with the following '
                                    'configuration parameter: "maxSupportedTransactionVersion": 1'})
        return {"version": 1}


async def test_get_transaction_upgrades_version_instead_of_missing_the_trade():
    rpc = _Rpc()
    assert await rpc.get_transaction("sig") == {"version": 1}
    assert rpc.seen_versions == [0, 1] and rpc.max_tx_version == 1


async def test_rate_limit_penalty_does_not_stack():
    from copybot.http_utils import RateLimiter

    rl = RateLimiter(4.0)
    for _ in range(8):  # eight concurrent requests all got 429
        rl.penalize(1.0)
    assert rl._tokens == -4.0  # one second of waiting, not eight
