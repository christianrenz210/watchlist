# migrate_db.py
import sqlite3
import os

def migrate_database():
    db_path = 'watchlist.db'
    
    if not os.path.exists(db_path):
        print(f"Database file '{db_path}' not found!")
        return
    
    print(f"Found database: {db_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check current columns
    cursor.execute("PRAGMA table_info(watchlist)")
    columns = [column[1] for column in cursor.fetchall()]
    
    print(f"Current columns: {columns}")
    
    # Add image_url column if it doesn't exist
    if 'image_url' not in columns:
        try:
            cursor.execute("ALTER TABLE watchlist ADD COLUMN image_url TEXT DEFAULT ''")
            print("✅ Successfully added 'image_url' column to watchlist table")
        except Exception as e:
            print(f"❌ Error adding column: {e}")
    else:
        print("ℹ️ 'image_url' column already exists")
    
    # Add total_episodes column if it doesn't exist (for older databases)
    if 'total_episodes' not in columns:
        try:
            cursor.execute("ALTER TABLE watchlist ADD COLUMN total_episodes INTEGER DEFAULT 0")
            print("✅ Successfully added 'total_episodes' column")
        except Exception as e:
            print(f"❌ Error adding total_episodes: {e}")
    
    conn.commit()
    conn.close()
    
    print("\nMigration completed!")
    
    # Verify the column was added
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(watchlist)")
    columns = [column[1] for column in cursor.fetchall()]
    print(f"Updated columns: {columns}")
    conn.close()

if __name__ == '__main__':
    migrate_database()