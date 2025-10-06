.PHONY: tunnel tunnel-quick dev deploy logs logs-mcp launch-mcp inspect-mcp

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

logs:
	@echo "=== Main App Logs ==="
	@fly logs -a assistant-summer-sun-6786 --no-tail | tail -20
	@echo ""
	@echo "=== MCP App Logs ==="
	@fly logs -a todoist-mcp --no-tail | tail -20

logs-mcp:
	fly logs -a todoist-mcp --no-tail | tail -20

launch-mcp:
	@./scripts/launch-mcp.sh

inspect-mcp:
	@./scripts/inspect-mcp.sh
