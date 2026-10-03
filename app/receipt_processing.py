import base64
import time
from datetime import datetime
from functools import lru_cache

from fastapi import UploadFile
from openai import BadRequestError, OpenAI

from .config import get_settings
from .firefly import (
    attach_image_to_transaction,
    create_firefly_transaction,
    get_firefly_budgets,
    get_firefly_categories,
)
from .image_utils import process_image
from .models import ReceiptModel


@lru_cache
def get_llm_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


# Structured-output request; strict mode needs every key required and no extras.
# Some providers require `strict` to be present even if they then ignore the
# schema (Anthropic's OpenAI-compatible endpoint does), so the prompt also asks
# for JSON and parse_receipt tolerates code fences.
RECEIPT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "receipt",
        "strict": True,
        "schema": {
            **ReceiptModel.model_json_schema(),
            "additionalProperties": False,
        },
    },
}


def request_completion(client: OpenAI, **kwargs):
    """Ask for schema-constrained JSON, retrying without it if the provider rejects it."""
    try:
        return client.chat.completions.create(
            **kwargs, response_format=RECEIPT_RESPONSE_FORMAT
        )
    except BadRequestError as e:
        if "response_format" not in str(e):
            raise
        print(f"Provider rejected response_format, retrying without it: {e}")
        return client.chat.completions.create(**kwargs)


def parse_receipt(text: str) -> ReceiptModel:
    """Parse the LLM JSON reply, tolerating ``` / ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```")
    return ReceiptModel.model_validate_json(text)


async def extract_receipt_data(file: UploadFile):
    """Extract data from the receipt image without creating a transaction."""
    try:
        print(f"Processing image: {file.filename}")

        # Process the image (resize and compress with more aggressive settings)
        image_b64, attachment_bytes = await process_image(file, max_size=(768, 768))
        print("Image processed and encoded to base64")

        # Fetch dynamic data from Firefly III
        print("Fetching categories and budgets...")
        categories = get_firefly_categories()
        budgets = get_firefly_budgets()
        print(
            f"Found {len(categories) if categories else 0} categories and {len(budgets) if budgets else 0} budgets"
        )

        # If we couldn't fetch categories or budgets, use default values
        if not categories:
            categories = [
                "Groceries",
                "Dining",
                "Shopping",
                "Transportation",
                "Entertainment",
                "Other",
            ]
            print("Using default categories due to Firefly III connection issues")

        if not budgets:
            budgets = ["Monthly", "Weekly", "Other"]
            print("Using default budgets due to Firefly III connection issues")

        # Construct the prompt.
        receipt_prompt = (
            "Please analyze the attached receipt image and extract the following details: "
            "1) receipt amount, 2) receipt category (choose from: "
            + ", ".join(categories)
            + "), "
            "3) receipt budget (choose from: " + ", ".join(budgets) + "), "
            "4) destination account (store name), "
            "5) description of the transaction, "
            "6) date (in YYYY-MM-DD format). Today's date is "
            + datetime.now().strftime("%Y-%m-%d")
            + ". "
            "Most receipts are from the past few days, so use today's date as a reference point when interpreting dates. "
            "If the date is not on the receipt, use today's date as the default. "
            "Respond with only a JSON object (no other text) with the keys: "
            "date, amount, store_name, description, category, budget."
        )

        # Set a shorter timeout for the API call
        try:
            print("Sending request to LLM for analysis...")
            settings = get_settings()
            client = get_llm_client()
            llm_response = request_completion(
                client,
                model=settings.llm_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": receipt_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
            )
            print("Received response from LLM")
            receipt = parse_receipt(llm_response.choices[0].message.content)
        except Exception as e:
            print(f"Error during LLM analysis: {str(e)}")
            print(f"Error type: {type(e)}")
            if "timeout" in str(e).lower():
                raise TimeoutError(
                    "The image processing timed out. Please try again with a smaller or clearer image."
                )
            raise e

        # Validate and format the date
        try:
            print(f"Validating date: {receipt.date}")
            # Try to parse the date to ensure it's valid
            date_obj = datetime.strptime(receipt.date, "%Y-%m-%d")
            # Format it back to the expected format
            receipt.date = date_obj.strftime("%Y-%m-%d")
            print("Date validation successful")
        except ValueError:
            # If the date is invalid, use the current date
            print(
                f"Invalid date format: {receipt.date}. Using current date instead."
            )
            receipt.date = datetime.now().strftime("%Y-%m-%d")

        # Return the extracted data as a dictionary
        extracted_data = {
            "date": receipt.date,
            "amount": receipt.amount,
            "store_name": receipt.store_name,
            "description": receipt.description,
            "category": receipt.category,
            "budget": receipt.budget,
            "available_categories": categories,
            "available_budgets": budgets,
            "image_base64": base64.b64encode(attachment_bytes).decode("ascii"),
        }
        print("Successfully extracted all data")
        return extracted_data
    except Exception as e:
        print(f"Unexpected error in extract_receipt_data: {str(e)}")
        print(f"Error type: {type(e)}")
        raise


async def create_transaction_from_data(receipt_data, source_account, image_bytes=None):
    """Create a transaction in Firefly III using the provided data."""
    # Create a ReceiptModel object from the data
    receipt = ReceiptModel(
        date=receipt_data["date"],
        amount=receipt_data["amount"],
        store_name=receipt_data["store_name"],
        description=receipt_data["description"],
        category=receipt_data["category"],
        budget=receipt_data["budget"],
    )

    # Implement retry logic with exponential backoff
    max_retries = 3  # Reduced from 5 to 3 to prevent too many duplicates
    retry_delay = 3  # Keep at 3 seconds
    last_error = None

    for attempt in range(max_retries):
        try:
            # Create a transaction based on the receipt data
            transaction_result = create_firefly_transaction(receipt, source_account)

            if transaction_result:
                print("Transaction created successfully:")
                print(f"- Date: {receipt.date}")
                print(f"- Amount: {receipt.amount}")
                print(f"- Store: {receipt.store_name}")
                print(f"- Category: {receipt.category}")
                print(f"- Budget: {receipt.budget}")
                print(f"- Source Account: {source_account}")
                print(f"- Transaction ID: {transaction_result['data']['id']}")
                message = f"Transaction created successfully with ID: {transaction_result['data']['id']}"

                # Attach outside the retry path so a failed upload never duplicates the transaction
                if image_bytes:
                    try:
                        journal_id = transaction_result["data"]["attributes"][
                            "transactions"
                        ][0]["transaction_journal_id"]
                        attach_image_to_transaction(
                            journal_id, image_bytes, f"receipt_{receipt.date}.jpg"
                        )
                    except Exception as e:
                        print(f"Warning: failed to attach receipt image: {e}")
                        message += " (attaching the receipt image failed)"
                return message
            else:
                last_error = (
                    "Failed to create transaction. No response from Firefly III."
                )
                print(last_error)

        except Exception as e:
            last_error = str(e)
            print(
                f"Error creating transaction (attempt {attempt + 1}/{max_retries}): {e}"
            )

            # If this is not the last attempt, wait and retry
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2**attempt)  # Exponential backoff
                print(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

    # If we've exhausted all retries, return an error message
    error_msg = f"Failed to create transaction after {max_retries} attempts. Last error: {last_error}"
    print(error_msg)
    return error_msg
