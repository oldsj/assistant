.PHONY: tunnel tunnel-quick dev deploy

# Quick temporary tunnel (random URL)
tunnel-quick:
	cloudflared tunnel --url http://localhost:5050

# Named tunnel with stable domain (requires setup first - see README)
tunnel:
	cloudflared tunnel --config ~/.cloudflared/assistant.yml run assistant

# Run the application
dev:
	uv run python main.py

deploy:
	fly deploy
