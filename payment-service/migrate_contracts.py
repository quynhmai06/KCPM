"""
Migration script to add signature fields to contracts table
Run this after starting the payment_service
"""
import os
import psycopg2
from psycopg2 import sql

# Database connection from environment
DB_HOST = os.getenv('DB_HOST', 'db')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'ev_platform')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')

def run_migration():
    """Run database migration"""
    conn = None
    try:
        # Connect to database
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        cur = conn.cursor()
        
        print("🔄 Running migration: Add signature fields to contracts table")
        
        # Add columns if they don't exist
        migrations = [
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS contract_status VARCHAR(50)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS buyer_signature_type VARCHAR(20)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS buyer_signature_data TEXT",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS buyer_signed_at TIMESTAMP",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS seller_signature_type VARCHAR(20)",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS seller_signature_data TEXT",
            "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS seller_signed_at TIMESTAMP",
        ]
        
        for migration_sql in migrations:
            cur.execute(migration_sql)
            print(f"✓ {migration_sql[:60]}...")
        
        # Set default status
        cur.execute("UPDATE contracts SET contract_status = 'draft' WHERE contract_status IS NULL")
        print(f"✓ Updated {cur.rowcount} contracts with default status")
        
        # Add indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_contracts_status ON contracts(contract_status)",
            "CREATE INDEX IF NOT EXISTS idx_contracts_buyer_signed ON contracts(buyer_signed_at)",
            "CREATE INDEX IF NOT EXISTS idx_contracts_seller_signed ON contracts(seller_signed_at)",
        ]
        
        for index_sql in indexes:
            cur.execute(index_sql)
            print(f"✓ {index_sql[:60]}...")
        
        # Commit changes
        conn.commit()
        
        # Display summary
        cur.execute("""
            SELECT 
                COUNT(*) as total_contracts,
                COUNT(buyer_signed_at) as buyer_signed_count,
                COUNT(seller_signed_at) as seller_signed_count,
                COUNT(CASE WHEN buyer_signed_at IS NOT NULL AND seller_signed_at IS NOT NULL THEN 1 END) as fully_signed_count
            FROM contracts
        """)
        
        row = cur.fetchone()
        if row:
            print("\n📊 Contract Summary:")
            print(f"   Total contracts: {row[0]}")
            print(f"   Buyer signed: {row[1]}")
            print(f"   Seller signed: {row[2]}")
            print(f"   Fully signed: {row[3]}")
        
        print("\n✅ Migration completed successfully!")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    run_migration()
