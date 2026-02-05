-- Supabase Schema for FaceCheck Telegram Bot
-- Run this in Supabase SQL Editor

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    free_searches INTEGER DEFAULT 1,
    paid_searches INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast telegram_id lookup
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);

-- Searches table (for tracking and unlocking)
CREATE TABLE IF NOT EXISTS searches (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
    search_id TEXT NOT NULL,
    results_count INTEGER DEFAULT 0,
    is_unlocked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_searches_telegram_id ON searches(telegram_id);
CREATE INDEX IF NOT EXISTS idx_searches_search_id ON searches(search_id);

-- Payments table
CREATE TABLE IF NOT EXISTS payments (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
    stars_amount INTEGER NOT NULL,
    searches_amount INTEGER DEFAULT 0,
    telegram_payment_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payments_telegram_id ON payments(telegram_id);

-- Gift Cards table
CREATE TABLE IF NOT EXISTS gift_cards (
    id BIGSERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    code_formatted TEXT NOT NULL,
    searches_amount INTEGER NOT NULL,
    batch_id TEXT,
    is_redeemed BOOLEAN DEFAULT FALSE,
    redeemed_by BIGINT REFERENCES users(telegram_id),
    redeemed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gift_cards_code ON gift_cards(code);
CREATE INDEX IF NOT EXISTS idx_gift_cards_redeemed_by ON gift_cards(redeemed_by);
CREATE INDEX IF NOT EXISTS idx_gift_cards_batch_id ON gift_cards(batch_id);

-- Gift Card Redemptions table (for tracking history)
CREATE TABLE IF NOT EXISTS gift_card_redemptions (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
    gift_card_id BIGINT NOT NULL REFERENCES gift_cards(id),
    searches_amount INTEGER NOT NULL,
    code TEXT NOT NULL,
    redeemed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gift_card_redemptions_telegram_id ON gift_card_redemptions(telegram_id);
CREATE INDEX IF NOT EXISTS idx_gift_card_redemptions_gift_card_id ON gift_card_redemptions(gift_card_id);

-- Enable Row Level Security (optional but recommended)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE gift_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE gift_card_redemptions ENABLE ROW LEVEL SECURITY;

-- Policy to allow service role full access
CREATE POLICY "Service role access" ON users FOR ALL USING (true);
CREATE POLICY "Service role access" ON searches FOR ALL USING (true);
CREATE POLICY "Service role access" ON payments FOR ALL USING (true);
CREATE POLICY "Service role access" ON gift_cards FOR ALL USING (true);
CREATE POLICY "Service role access" ON gift_card_redemptions FOR ALL USING (true);
