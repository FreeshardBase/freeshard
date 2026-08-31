-- shard-core-0005-owner-email-verification
-- depends: shard-core-0004-oidc

-- users.email becomes the single home for a person's address, and it is
-- verified by definition. pending_email holds an unverified candidate, at most
-- one per user, together with the digest and expiry of its confirmation token.
ALTER TABLE users ADD COLUMN pending_email TEXT;
ALTER TABLE users ADD COLUMN email_token_hash TEXT;
ALTER TABLE users ADD COLUMN email_token_expires TIMESTAMPTZ;

-- the two token columns are only ever written together
ALTER TABLE users ADD CONSTRAINT users_email_token_paired
    CHECK ((email_token_hash IS NULL) = (email_token_expires IS NULL));

-- identities.email was editable on the Public page and never verified, so it
-- carries over as a candidate rather than as the owner's verified address.
-- NULLIF because the dropped column defaulted to '' rather than NULL on the
-- Public page, and an empty candidate is one nobody can ever confirm.
UPDATE users
SET pending_email = NULLIF(
    (SELECT email FROM identities WHERE is_default = TRUE LIMIT 1), '')
WHERE role = 'owner';

-- Every users.email written so far is either the synthetic owner@<domain> or an
-- unverified copy of identities.email. Neither may be asserted as verified, so
-- every shard lands with no verified address.
UPDATE users SET email = NULL WHERE role = 'owner';

-- An identity is the shard's public profile, published unauthenticated by
-- GET /public/meta/whoareyou; a personal address has no business there.
ALTER TABLE identities DROP COLUMN email;
