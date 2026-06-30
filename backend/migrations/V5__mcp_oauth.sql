ALTER TABLE mcp_server_configs ADD COLUMN auth_type TEXT NOT NULL DEFAULT 'none';
ALTER TABLE mcp_server_configs ADD COLUMN oauth_config TEXT;
ALTER TABLE mcp_server_configs ADD COLUMN oauth_token TEXT;
