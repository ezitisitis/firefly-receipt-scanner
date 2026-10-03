# Receipt Scanner for Firefly III

A web application that allows you to scan receipts and automatically create transactions in Firefly III.

## Demo

Check out the demo video below to see the Receipt Scanner in action:


https://github.com/user-attachments/assets/ec41d8dc-71e9-4aa4-b65c-869c3dd54845

## Features

- Upload and scan receipts using any vision-capable LLM (Gemini, OpenAI, Claude, Ollama, ...)
- Extract key information: date, amount, store name, category, and budget
- Review and edit extracted data before creating transactions
- Create transactions in Firefly III with a single click
- Automatically adds an `#automated` tag to all created transactions
- Take a photo with the camera or pick an existing image from your gallery/files
- Optionally attaches the receipt image (JPEG, max 1600px) to the created transaction (pre-ticked by default, set `ATTACH_RECEIPT_DEFAULT=false` in `.env` to change)
- Mobile-friendly interface for scanning receipts on the go

## Prerequisites

- Docker and Docker Compose
- A Firefly III instance
- An API key for an OpenAI-compatible LLM provider (Google Gemini by default)

## Configuration

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/receipt-scanner.git
   cd receipt-scanner
   ```

2. Create a `.env` file based on the `.env.example`:
   ```
   cp .env.example .env
   ```

3. Edit the `.env` file with your configuration:
   ```
   # Firefly III API Configuration
   FIREFLY_III_URL=https://your-firefly-iii-instance.com
   FIREFLY_III_TOKEN=your-personal-access-token

   # LLM Configuration
   LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   LLM_API_KEY=your-llm-api-key
   LLM_MODEL=gemini-2.5-flash
   IMAGE_QUALITY=85
   ```
   
### Requesting Firefly III Token

   To use this application, you'll need a personal access token for Firefly III. Follow the instructions in the official documentation to generate one: [Firefly III API - Personal Access Tokens](https://docs.firefly-iii.org/how-to/firefly-iii/features/api/#personal-access-tokens)

### LLM Provider

   Any provider with an OpenAI-compatible chat completions API and a vision-capable model works. Set `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL`:

   | Provider | `LLM_BASE_URL` | Example `LLM_MODEL` | API key |
   |---|---|---|---|
   | Google Gemini (default) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-2.5-flash` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
   | OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
   | Anthropic Claude | `https://api.anthropic.com/v1/` | `claude-sonnet-5-5` | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
   | Ollama (local) | `http://<host>:11434/v1` | `qwen2.5vl` | none (any non-empty value, e.g. `ollama`) |
   | OpenRouter | `https://openrouter.ai/api/v1` | `google/gemini-2.5-flash` | [openrouter.ai/keys](https://openrouter.ai/keys) |
   | Mistral | `https://api.mistral.ai/v1` | `pixtral-12b-2409` | [console.mistral.ai](https://console.mistral.ai/api-keys) |

   The old `GOOGLE_AI_API_KEY` and `GEMINI_MODEL` variables are still accepted as fallbacks for `LLM_API_KEY` and `LLM_MODEL`, so existing `.env` files keep working.

   `IMAGE_QUALITY` (1-100, default `85`) sets the JPEG quality of the receipt image sent to the LLM. Lower it to save bandwidth/tokens, raise it if small print is misread.

## Deployment
### Security and Deployment Considerations

This application does not include built-in authentication. It is recommended to deploy it within your local network, ideally alongside your Firefly III instance. To securely access the application remotely, consider using a VPN to connect to your local network.

### Using Docker Compose (Recommended)

1. Build and start the application:
   ```
   docker-compose up -d
   ```

2. Access the application at http://localhost:8000

### Manual Deployment

1. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the application:
   ```
   uvicorn app.app:app --host 0.0.0.0 --port 8000
   ```

## Usage
   1. Open the application in your web browser
   2. Select a source account from the dropdown menu
   3. Use the camera to take a photo of your receipt, or choose an existing image
   4. Review and edit the extracted data; untick "Attach receipt image to transaction" (default set by `ATTACH_RECEIPT_DEFAULT`) if you don't want the image stored in Firefly III
   5. Click "Create Transaction" to create the transaction in Firefly III

If you're using a phone, consider adding a bookmark of the app to your home screen for easier access.
![iPhone Usage](docs/images/bookmark.jpg)



## Updating

To update to the latest version:

1. Pull the latest changes:
   ```
   cd firefly-receipt-scanner
   git pull
   ```

2. Check `.env.example` for any new environment variables and add them to your `.env` file if needed.

3. Rebuild and restart the containers:
   ```
   docker-compose up -d --build
   ```

Your `.env` file will not be affected by the update.

## Troubleshooting

### Common Issues

- **Image Processing Timeout**: If you receive a timeout error when processing an image, try using a clearer image with better lighting and less glare.
- **Transaction Creation Failed**: If transaction creation fails, check your Firefly III connection and ensure your API token has the necessary permissions.
- **Camera Not Working**: Ensure your browser has permission to access your camera. For mobile devices, you may need to use HTTPS.

## Development

### Project Structure

- `app/` - Application code
  - `app.py` - FastAPI application and routes
  - `firefly.py` - Firefly III API integration
  - `receipt_processing.py` - Receipt data extraction and processing
  - `image_utils.py` - Image processing utilities
  - `models.py` - Data models
  - `templates/` - HTML templates
  - `static/` - Static assets (CSS, JavaScript)


## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

If you find this project useful, you can support it via [GitHub Sponsors](https://github.com/sponsors/ezitisitis) or [Buy Me a Coffee](https://buymeacoffee.com/ezitisitis).

Crypto:

- ETH: `0x1732b7b8d490e5114754702E9bF07dE61AA63691`
- BTC: `bc1qwczllcjeen7yzpj50dn950t6m82ryggf9pkhas`
- Tron (TRC20): `TJQK7UQVNGwavkCXmitUHVCFcRfMdZQAHs`

## License

MIT
