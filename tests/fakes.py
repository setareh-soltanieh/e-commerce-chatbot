from shopbot.seed_data import CUSTOMERS, POLICIES, PRODUCTS, build_orders


class FakeStore:
    """An in-memory stand-in for SupabaseStore."""

    def __init__(self):
        self.products = {product["sku"]: product for product in PRODUCTS}
        self.orders = build_orders()
        self.returns = []
        self.tickets = []

    def get_customer(self, customer_id):
        return next((c for c in CUSTOMERS if c["id"] == customer_id), None)

    def list_orders(self, customer_id):
        return [o for o in self.orders if o["customer_id"] == customer_id]

    def get_order(self, customer_id, order_id):
        for order in self.orders:
            if order["id"] == order_id and order["customer_id"] == customer_id:
                return order | {"products": self.products[order["sku"]]}
        return None

    def search_products(self, query, max_price=None):
        words = query.lower().split()
        return [
            p for p in self.products.values()
            if any(w in f"{p['name']} {p['description']} {p['category']}".lower() for w in words)
            and (max_price is None or p["price"] <= max_price)
        ]

    def get_product(self, sku):
        return self.products.get(sku)

    def get_policy(self, topic):
        return next((p for p in POLICIES if p["topic"] == topic), None)

    def create_return(self, customer_id, order_id, reason):
        record = {"id": f"R{len(self.returns)}", "order_id": order_id, "customer_id": customer_id, "reason": reason}
        self.returns.append(record)
        return record

    def create_ticket(self, customer_id, reason):
        record = {"id": f"T{len(self.tickets)}", "customer_id": customer_id, "reason": reason}
        self.tickets.append(record)
        return record


class FakeSearch:
    def __init__(self):
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return f"web results for {query}"
