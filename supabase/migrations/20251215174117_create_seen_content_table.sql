/*
  # SeenIt - Content Tracking Schema

  ## Overview
  Creates the core database structure for the SeenIt Chrome extension, which tracks web content
  that users have already seen.

  ## New Tables
  
  ### `seen_content`
  Stores information about web pages that users have marked as seen.
  
  - `id` (uuid, primary key) - Unique identifier for each seen content entry
  - `user_id` (uuid, foreign key) - References auth.users, identifies content owner
  - `url` (text, required) - The full URL of the seen webpage
  - `title` (text, required) - The title of the webpage
  - `content_hash` (text, optional) - Future: Hash for content similarity detection
  - `favicon` (text, optional) - URL to the page's favicon for visual identification
  - `seen_at` (timestamptz) - Timestamp when content was first marked as seen
  - `hide_similar` (boolean) - Flag indicating if similar content should be auto-hidden
  - `updated_at` (timestamptz) - Timestamp of last update

  ## Security
  
  ### Row Level Security (RLS)
  - Enabled on `seen_content` table to ensure data privacy
  - Users can only read their own seen content
  - Users can only insert their own seen content
  - Users can only update their own seen content
  - Users can only delete their own seen content

  ## Indexes
  - Index on `user_id` for fast user-specific queries
  - Index on `url` for duplicate detection
  - Composite index on `user_id, url` for checking if specific URL is seen by user

  ## Notes
  - All timestamps use `timestamptz` for proper timezone handling
  - `content_hash` field is prepared for future NLP/similarity detection features
  - The schema supports the minimal viable product while allowing future enhancements
*/

CREATE TABLE IF NOT EXISTS seen_content (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  url text NOT NULL,
  title text NOT NULL,
  content_hash text,
  favicon text,
  seen_at timestamptz DEFAULT now() NOT NULL,
  hide_similar boolean DEFAULT false NOT NULL,
  updated_at timestamptz DEFAULT now() NOT NULL
);

ALTER TABLE seen_content ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own seen content"
  ON seen_content
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own seen content"
  ON seen_content
  FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own seen content"
  ON seen_content
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own seen content"
  ON seen_content
  FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_seen_content_user_id ON seen_content(user_id);
CREATE INDEX IF NOT EXISTS idx_seen_content_url ON seen_content(url);
CREATE INDEX IF NOT EXISTS idx_seen_content_user_url ON seen_content(user_id, url);

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'update_seen_content_updated_at'
  ) THEN
    CREATE TRIGGER update_seen_content_updated_at
      BEFORE UPDATE ON seen_content
      FOR EACH ROW
      EXECUTE FUNCTION update_updated_at_column();
  END IF;
END $$;
