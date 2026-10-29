import base64
import os
import sys

from fastapi import (
    FastAPI,
    File,
    Form,
    Request,
    UploadFile,
)
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import get_settings
from .firefly import (
    get_firefly_asset_accounts,
    get_firefly_asset_accounts_detailed,
    get_firefly_categories,
)
from .matching import assign_matches, convert, find_matches
from .receipt_processing import (
    create_transaction_from_data,
    extract_receipt_data,
    update_transaction_from_data,
)


def test_firefly_connection():
    """Test the connection to Firefly III by attempting to fetch categories."""
    try:
        categories = get_firefly_categories()
        if categories is None:
            print("Error: Could not connect to Firefly III. Categories returned None.")
            return False
        print("Successfully connected to Firefly III")
        return True
    except Exception as e:
        print(f"Error connecting to Firefly III: {str(e)}")
        return False


app = FastAPI(title="Receipt to Firefly III")

# Add ProxyHeadersMiddleware to trust X-Forwarded-Proto and X-Forwarded-Host from reverse proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Test Firefly III connection before proceeding
if not test_firefly_connection():
    print("Failed to establish connection to Firefly III. Exiting...")
    sys.exit(1)

# Add trusted host middleware to handle forwarded headers
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

# Create a static directory if it doesn't exist
os.makedirs("app/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Set up templates
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["attach_receipt_default"] = get_settings().attach_receipt_default
templates.env.globals["firefly_url"] = get_settings().firefly_iii_url
templates.env.globals["match_existing_default"] = get_settings().match_existing_default
templates.env.globals["match_date_window_days"] = get_settings().match_date_window_days


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Serve a simple HTML form for uploading receipts."""
    # Fetch asset accounts from Firefly III
    asset_accounts = get_firefly_asset_accounts()

    # If no accounts were fetched, use a default
    if not asset_accounts:
        asset_accounts = ["Cash wallet"]
        print("Using default asset account due to Firefly III connection issues")

    return templates.TemplateResponse(
        "upload.html", {"request": request, "asset_accounts": asset_accounts}
    )


def find_account(name):
    return next(
        (a for a in get_firefly_asset_accounts_detailed() if a["name"] == name), None
    )


async def prepare_receipt(file, source_account, account, match_existing, window_days):
    """Extract one receipt, convert foreign amounts and look up matching transactions."""
    data = await extract_receipt_data(file)
    data["source_account"] = source_account
    data["filename"] = file.filename

    currency = data.get("currency") or ""
    account_currency = (account or {}).get("currency_code")
    if currency and account_currency and currency != account_currency:
        # Firefly III wants the amount in the account currency; keep the receipt's as foreign
        data["foreign_amount"] = data["amount"]
        data["foreign_currency"] = currency
        converted = convert(data["amount"], currency, account_currency)
        data["amount"] = round(converted, 2) if converted else ""
    data["account_currency"] = account_currency or ""

    data["match_checked"] = bool(match_existing and account)
    data["candidates"] = (
        find_matches(data, account, window_days) if data["match_checked"] else []
    )
    return data


@app.post("/extract")
async def extract_receipt(
    request: Request,
    file: list[UploadFile] = File(...),
    source_account: str = Form(...),
    match_existing: bool = Form(False),
    window_days: int | None = Form(None),
):
    if window_days is None:
        window_days = get_settings().match_date_window_days
    window_days = max(window_days, 0)
    account = find_account(source_account)

    if len(file) > 1:
        receipts = []
        for upload in file:
            try:
                receipts.append(
                    await prepare_receipt(
                        upload, source_account, account, match_existing, window_days
                    )
                )
            except Exception as e:
                receipts.append({"filename": upload.filename, "error": str(e)})
        assign_matches([r for r in receipts if "error" not in r])
        return templates.TemplateResponse(
            "review_bulk.html",
            {
                "request": request,
                "receipts": receipts,
                "source_account": source_account,
            },
        )

    try:
        # Process the image and extract data
        extracted_data = await prepare_receipt(
            file[0], source_account, account, match_existing, window_days
        )
        assign_matches([extracted_data])

        return templates.TemplateResponse(
            "review.html", {"request": request, "extracted_data": extracted_data}
        )
    except TimeoutError:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "error_message": "The operation timed out. The image processing is taking too long. Please try again with a smaller or clearer image.",
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            "error.html", {"request": request, "error_message": str(e)}
        )


def foreign_fields(foreign_amount, foreign_currency, account_currency):
    """Foreign amount and currency to store, or empty when not in another currency."""
    currency = (foreign_currency or "").strip().upper()
    if not foreign_amount or not currency or currency == (account_currency or "").upper():
        return "", ""
    return foreign_amount, currency


async def submit_receipt(data, source_account, match, overwrite, image_bytes):
    """Create a new withdrawal, or update the matched one ("<group_id>:<journal_id>")."""
    if match and match != "new":
        group_id, journal_id = match.split(":")
        return await update_transaction_from_data(
            data, group_id, journal_id, overwrite, image_bytes
        )
    return await create_transaction_from_data(data, source_account, image_bytes)


@app.post("/create-transaction")
async def create_transaction(
    request: Request,
    date: str = Form(...),
    amount: float = Form(...),
    store_name: str = Form(...),
    description: str = Form(...),
    category: str = Form(...),
    budget: str = Form(...),
    source_account: str = Form(...),
    attach_receipt: bool = Form(False),
    image_base64: str = Form(""),
    foreign_amount: str = Form(""),
    foreign_currency: str = Form(""),
    account_currency: str = Form(""),
    match: str = Form("new"),
):
    try:
        image_bytes = (
            base64.b64decode(image_base64) if attach_receipt and image_base64 else None
        )
        form = await request.form()
        journal_id = match.partition(":")[2]
        foreign_amount, foreign_currency = foreign_fields(
            foreign_amount, foreign_currency, account_currency
        )

        # Create the transaction, or update the matched one
        result = await submit_receipt(
            {
                "date": date,
                "amount": amount,
                "store_name": store_name,
                "description": description,
                "category": category,
                "budget": budget,
                "source_account": source_account,
                "foreign_amount": foreign_amount,
                "foreign_currency": foreign_currency,
            },
            source_account,
            match,
            form.getlist(f"overwrite_{journal_id}"),
            image_bytes,
        )

        if result and "Failed to create transaction" in result:
            return templates.TemplateResponse(
                "error.html", {"request": request, "error_message": result}
            )

        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "asset_accounts": get_firefly_asset_accounts(),
                "success_message": (
                    "Transaction created successfully!"
                    if match == "new"
                    else "Existing transaction updated with the receipt!"
                )
                + (
                    " Attaching the receipt image failed."
                    if "attaching the receipt image failed" in result
                    else ""
                ),
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            "error.html", {"request": request, "error_message": str(e)}
        )


@app.post("/create-transactions")
async def create_transactions(request: Request):
    """Submit the bulk review page: rows are prefixed r0_, r1_, ..."""
    form = await request.form()
    source_account = form.get("source_account", "")
    created = updated = skipped = 0
    errors = []
    used = set()

    for i in range(int(form.get("count", 0))):
        prefix = f"r{i}_"
        label = form.get(prefix + "filename") or f"Receipt {i + 1}"
        match = form.get(prefix + "match", "new")
        if match == "skip":
            skipped += 1
            continue
        try:
            journal_id = match.partition(":")[2]
            if journal_id and journal_id in used:
                raise Exception("its transaction is already matched by another receipt")
            data = {
                key: form.get(prefix + key, "")
                for key in [
                    "date",
                    "store_name",
                    "description",
                    "category",
                    "budget",
                    "foreign_amount",
                    "foreign_currency",
                ]
            }
            amount = form.get(prefix + "amount", "")
            if not amount and not journal_id:
                raise Exception("the amount is missing")
            data["amount"] = float(amount or 0)
            data["foreign_amount"], data["foreign_currency"] = foreign_fields(
                data["foreign_amount"],
                data["foreign_currency"],
                form.get(prefix + "account_currency"),
            )
            data["source_account"] = source_account
            image_base64 = form.get(prefix + "image_base64", "")
            image_bytes = (
                base64.b64decode(image_base64)
                if form.get(prefix + "attach_receipt") and image_base64
                else None
            )
            result = await submit_receipt(
                data,
                source_account,
                match,
                form.getlist(f"{prefix}overwrite_{journal_id}"),
                image_bytes,
            )
            if "Failed to create transaction" in result:
                raise Exception(result)
            if journal_id:
                used.add(journal_id)
                updated += 1
            else:
                created += 1
            if "attaching the receipt image failed" in result:
                errors.append(f"{label}: attaching the receipt image failed")
        except Exception as e:
            errors.append(f"{label}: {e}")

    return templates.TemplateResponse(
        "upload.html",
        {
            "request": request,
            "asset_accounts": get_firefly_asset_accounts(),
            "success_message": f"{created} created, {updated} matched and updated, {skipped} skipped.",
            "errors": errors,
        },
    )
