"""Adapter: gives c4's apply_enforcement() the small `db` interface it expects, on top of c1's Supabase helper."""


class StoreEnforcementDb:
    def __init__(self, store):
        self.store = store          # the `db` module (or a test double)

    def update_order(self, order_id, fields):
        self.store.update_order(order_id, fields)

    def get_order_items(self, order_id):
        return self.store.get_order_items(order_id)

    def get_catalog(self):
        return self.store.get_catalog()

    def insert_restriction(self, user_id, type, minutes, reason):
        self.store.insert_restriction(user_id, type, minutes, reason)

    def insert_audit(self, payload):
        self.store.insert_audit_row(payload)
