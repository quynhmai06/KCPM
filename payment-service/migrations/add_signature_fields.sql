-- Migration script to add signature fields to contracts table
-- Run this after updating the model

ALTER TABLE contracts 
ADD COLUMN IF NOT EXISTS contract_status VARCHAR(50),
ADD COLUMN IF NOT EXISTS buyer_signature_type VARCHAR(20),
ADD COLUMN IF NOT EXISTS buyer_signature_data TEXT,
ADD COLUMN IF NOT EXISTS buyer_signed_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS seller_signature_type VARCHAR(20),
ADD COLUMN IF NOT EXISTS seller_signature_data TEXT,
ADD COLUMN IF NOT EXISTS seller_signed_at TIMESTAMP;

-- Set default status for existing contracts
UPDATE contracts 
SET contract_status = 'draft' 
WHERE contract_status IS NULL;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(contract_status);
CREATE INDEX IF NOT EXISTS idx_contracts_buyer_signed ON contracts(buyer_signed_at);
CREATE INDEX IF NOT EXISTS idx_contracts_seller_signed ON contracts(seller_signed_at);

-- Display summary
SELECT 
    COUNT(*) as total_contracts,
    COUNT(buyer_signed_at) as buyer_signed_count,
    COUNT(seller_signed_at) as seller_signed_count,
    COUNT(CASE WHEN buyer_signed_at IS NOT NULL AND seller_signed_at IS NOT NULL THEN 1 END) as fully_signed_count
FROM contracts;
