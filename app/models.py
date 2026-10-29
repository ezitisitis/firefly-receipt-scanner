from pydantic import BaseModel


class ReceiptModel(BaseModel):
    date: str
    amount: float
    store_name: str
    description: str
    category: str
    budget: str
    # ISO 4217 code printed on the receipt, empty if unknown
    currency: str = ""
