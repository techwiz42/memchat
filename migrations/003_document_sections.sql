-- Add sections_json column for chunked editing of large documents
ALTER TABLE conversation_documents ADD COLUMN IF NOT EXISTS sections_json JSONB;
