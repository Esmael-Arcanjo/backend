from app.core.repository import BaseRepository


class WalletRepository(BaseRepository):
    collection_name = "wallets"


class WalletTransactionRepository(BaseRepository):
    collection_name = "balances"


class TransferRepository(BaseRepository):
    collection_name = "transfers"
